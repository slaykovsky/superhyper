#!/usr/bin/env python3
import asyncio
import uuid
import json
import ipaddress
import os
import sys

import aiofiles

DATA = {}

data_path = os.path.dirname(sys.argv[0])
vms_path = os.path.join(data_path, 'vms')
disks_path = os.path.join(data_path, 'disks')
kernel_path = os.path.join(data_path, 'kernel')

for p in [vms_path, disks_path, kernel_path]:
    if not os.path.exists(p):
        os.makedirs(p)


def is_running(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def write_string(writer, message):
    writer.write(f'{message}\n'.encode())


async def handle_rpc(reader, writer):
    data = await reader.read()
    message = data.decode()
    addr = writer.get_extra_info('peername')

    print(f"Received {message!r} from {addr!r}")
    data = json.loads(message)

    async def close_writer():
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    if "action" not in data:
        write_string(writer, 'No action defined')
        await close_writer()
        return

    action = data['action'].strip()
    data['action'] = action
    if not data.get("vm_name") and action in ['start', 'stop', 'kill', 'address']:
        write_string(writer, 'No VM name is given')
        await close_writer()
        return

    vm_name = data.get('vm_name', '').strip()
    data['vm_name'] = vm_name

    def validate():
        if action in ['stop', 'address', 'kill']:
            if vm_name not in DATA:
                return False, f'No such VM {vm_name} is running'

        elif action == 'start':
            if vm_name in DATA:
                return False, f'VM {vm_name} is already started'

        return True, None

    valid, msg = validate()
    if not valid:
        write_string(writer, msg)
        await close_writer()
        return

    actions = {}
    actions['start'] = handle_start
    actions['stop'] = handle_stop
    actions['kill'] = handle_stop
    actions['available'] = handle_available
    actions['address'] = handle_address
    actions['list'] = handle_list

    await actions[action](writer, data)

    await close_writer()


async def handle_list(writer, data):
    for vm_name in list(DATA):
        vm, _ = DATA[vm_name]

        if not is_running(vm.pid):
            del DATA[vm_name]

    if not DATA:
        write_string(writer, 'No running VMs')
        return

    write_string(writer, 'Currently running VMs are:')

    for vm_name in DATA.keys():
        write_string(writer, f'\t{vm_name}')


async def handle_available(writer, data):
    write_string(writer, 'Available VMs:')

    for vm in os.listdir(vms_path):
        name, ext = os.path.splitext(vm)

        if ext != '.shadow':
            continue
        write_string(writer, f'\t{name}')


async def handle_start(writer, data):
    vm_name = data['vm_name']
    cpu = data['cpu']
    memory = data['memory']

    write_string(writer, f'Starting VM {vm_name}\n')

    attach_disk = await asyncio.create_subprocess_shell(
        f'hdiutil attach -nomount -noverify -noautofsck -shadow {data_path}/vms/{vm_name}.shadow {data_path}/disks/centos.dmg | head -n1 | cut -f1 -d " "',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await attach_disk.communicate()
    if stdout:
        disk = stdout.decode().strip()
    if stderr:
        print(f'[stderr]\n{stderr.decode()}')
        write_string(writer, 'There was an error whilst attaching an image')
        return

    rdisk = disk.replace("disk", "rdisk")

    vm_stdin_path = f'/tmp/stdin_{vm_name}'
    vm_stdout_path = f'/tmp/stdout_{vm_name}'

    vm_start_cmd = " ".join([
        "hyperkit", '-w', '-A', '-H', '-P', f'-m {memory}', f'-c {cpu}',
        '-s 0:0,hostbridge', '-s 31,lpc', f'-l com1,stdio,autopty={vm_stdin_path},asl,log={vm_stdout_path}',
        f'-s 1:0,virtio-blk,{rdisk}', '-s 2:0,virtio-net', '-s 6,virtio-rnd',
        f'-f kexec,{data_path}/kernel/vmlinuz,{data_path}/kernel/initrd.gz,"root=/dev/vda3 earlyprintk=serial console=ttyS0 quiet zswap.enabled"',
        f'-U {uuid.uuid3(uuid.NAMESPACE_OID, vm_name)}'
    ])

    vm = await asyncio.create_subprocess_shell(
        vm_start_cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL
    )
    DATA[vm_name] = (vm, disk)

    write_string(writer, f'VM {vm_name} started')


async def handle_stop(writer, data):
    vm_name = data['vm_name']
    action = data['action']
    vm, disk = DATA[vm_name]

    if not is_running(vm.pid):
        write_string(writer, f'VM {vm_name} is already stopped')
        if vm_name in DATA:
            del DATA[vm_name]
        return

    actions = {}
    actions['stop'] = vm.terminate
    actions['kill'] = vm.kill

    write_string(writer, f'Attempting to {action} VM {vm_name}')

    actions[action]()

    await vm.wait()

    del DATA[vm_name]

    detach_disk = await asyncio.create_subprocess_shell(
        f'hdiutil detach {disk}',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await detach_disk.communicate()
    if stdout:
        print(f'[stdout]\n{stdout.decode()}')
    if stderr:
        print(f'[stderr]\n{stderr.decode()}')
        write_string(writer, f'Error occured whilst detaching VM\'s disk {vm_name}')
        write_string(writer, 'Please check server logs')

    write_string(writer, f'VM {vm_name} is stopped')


async def handle_address(writer, data):
    vm_name = data['vm_name']

    async def get_ip():
        tries = 10
        while tries > 0:
            async with aiofiles.open(f'/tmp/stdin_{vm_name}', mode='w') as f:
                await f.write("ip a | grep 'scope global' | grep --color=never -Po '(?<=inet )[\d.]+'\n")
                await f.flush()
            async with aiofiles.open(f'/tmp/stdout_{vm_name}', mode='r') as f:
                async for line in f:
                    try:
                        return ipaddress.ip_address(line.strip())
                    except ValueError:
                        pass
            await asyncio.sleep(1)
            tries -= 1
        return None

    ip = await get_ip()
    if ip is None:
        write_string(writer, 'No IP can be determined. Try a bit later...')
        return

    write_string(writer, f'VM {vm_name} IP is {ip}')

async def main():
    server = await asyncio.start_server(
        handle_rpc, '127.0.0.1', 7593
    )

    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
