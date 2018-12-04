#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys

ACTIONS = ['start', 'stop', 'kill', 'list', 'address', 'available']

parser = argparse.ArgumentParser(sys.argv[0])
parser.add_argument('action', help=f'Action to perform ({"|".join(ACTIONS)})', type=str)
parser.add_argument('vm_name', default=None, nargs='?', help='Virtual Machine name', type=str)
parser.add_argument('--memory', default='1G', required=False, help='Virtual Machine memory (e.g. 1G)', type=str)
parser.add_argument('--cpu', default=1, required=False, help='Virtual Machine CPU (e.g. 1)', type=int)

async def tcp_rpc_client(message):
    reader, writer = await asyncio.open_connection(
        host='127.0.0.1', port=7593
    )
    writer.write(message.encode())
    await writer.drain()
    writer.write_eof()

    data = await reader.read()

    print(data.decode())
    writer.close()
    await writer.wait_closed()

args = parser.parse_args()

action = args.action
vm_name = args.vm_name

if action not in ACTIONS:
    raise NotImplementedError('Action you seek to perform is not yet implemented!')
if not vm_name and action in ['start', 'stop', 'kill', 'address']:
    raise ValueError('You should have vm_name whilst using one of start, stop and kill actions.')

if action == "start":
    data = {
        "action": action,
        "vm_name": vm_name,
        "memory": args.memory,
        "cpu": args.cpu
    }
elif action in ["list", "available"]:
    data = {"action": action}
elif action in ["stop", "kill", "address"]:
    data = {"action": action, "vm_name": vm_name}

asyncio.run(tcp_rpc_client(json.dumps(data)))