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

async def handle_rpc(reader, writer):
    data = await reader.read()
    message = data.decode()
    addr = writer.get_extra_info('peername')

    print(f"Received {message!r} from {addr!r}")
    data = json.loads(message)
    fuck_off = False

    async def close_writer():
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    if "action" not in data:
        writer.write("No action defined.\n".encode())
        await close_writer()
        return

    action = data['action'].strip()
    if not data.get("vm_name") and action in ['start', 'stop', 'kill', 'address']:
        writer.write("No vm name given.\n".encode())
        await close_writer()
        return

    vm_name = data.get('vm_name', '').strip()

    def validate():
        if action in ['stop', 'address', 'kill']:
            if vm_name not in DATA:
                return False, f'No such VM {vm_name} is running\n'.encode()

        if action == "list" and not DATA:
            return False, 'No running VMs.\n'.encode()

        elif action == 'start':
            if vm_name in DATA:
                return False, f'VM {vm_name} is already started.\n'.encode()

        return True, None

    valid, msg = validate()
    if not valid:
        writer.write(msg)
        await close_writer()
        return

    if action == "start":
        cpu = data['cpu']
        memory = data['memory']
        writer.write(f"Staring VM {vm_name}\n".encode())
        ret = await handle_start(vm_name, cpu, memory)
        writer.write(ret.encode())

    elif action in ["stop", "kill"]:
        writer.write(f'Attempting to {action} VM {vm_name}\n'.encode())
        await handle_stop(vm_name, action)
        writer.write(f'Done {action} VM {vm_name}\n'.encode())
    elif action == "list":
        writer.write('Currently running VMs are:\n'.encode())
        for vname in DATA.keys():
            writer.write(f'\t{vname}\n'.encode())
    elif action == "available":
        writer.write('Available VMs:\n'.encode())
        for vm in os.listdir(vms_path):
            if 'shadow' not in vm:
                continue
            writer.write(f'\t{os.path.splitext(vm)[0]}\n'.encode())
    elif action == "address":
        ip = await handle_address(vm_name)
        if ip is None:
            writer.write(f'No IP can be determined. Try a bit later...\n'.encode())
        else:
            writer.write(f'VM {vm_name} ip is {ip}\n'.encode())

    await close_writer()


async def handle_start(vm_name, cpu, memory):
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

    return f'VM {vm_name} started'


async def handle_stop(vm_name, action):
    vm, disk = DATA[vm_name]

    if action == "stop":
        vm.terminate()
    elif action == "kill":
        vm.kill()

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


async def handle_address(vm_name):
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
