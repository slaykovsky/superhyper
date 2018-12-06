# SuperHyper
**Please note it contains >>LOTS<< of bugs**

*Really early development*

A tool to run GNU/Linux virtual machines on [hyperkit](https://github.com/moby/hyperkit).

You need to have Linux kernel and initramfs and put them into `kernel` directory.

The other thing is to have [hyperkit](https://github.com/moby/hyperkit) binary in your PATH.

Also, you really need to have a root disk image of your linux.
You can take one [here](https://mega.nz/#!MdFxhKrB!belhQVcQ4dyrVe4f4wrIi65eldmPCdFKv6u1lb3hfMo).
Be careful it's 8 gigs ;) Place it in the `disks` directory.

To run server just start `server.py` with super user privileges. It needs privileges to activate networking for a VM.

To explore what you can do now, run `client.py -h` as regular user.
