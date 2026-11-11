# Running the HW4 judge

Use your own previous `q2/src/run.c`; merge the new interface and helpers.
The supplied TODO runner is intentionally incomplete. Do not replace working
student code with the blank runner. The Persian handout defines requirements.
Keep `src/image_helper.py` beside the binary's `src/` directory from HW7 onward.

## Langar Lab

Install the helper using [the usage guide](LANGAR-LAB.md). It includes
prerequisites, native/VM setup and troubleshooting. Run from the repository root:

```sh
./.langar-lab/bin/langar-lab setup
./.langar-lab/bin/langar-lab test hw4 --source ./q2 --json ./result.json
```

Linux defaults to native; macOS/Windows use the owned Multipass VM. Choose
`--backend native` or `--backend multipass`. Windows PowerShell can invoke
`.\.langar-lab\bin\langar-lab.exe`; Bash is not required on the host.
A trusted supervisor uses `sudo -n`; builds and workloads run in separate Bubblewrap sandboxes as unprivileged host UID 65534. Judge files and reports are outside the writable sandbox. On native Linux, enable this
by running `sudo -v` in the same terminal before the CLI. For an ordinary native
account without noninteractive sudo, use the VM backend or run the manual judge.

## Directly in Linux

```sh
sudo apt install build-essential python3 busybox-static util-linux procps bubblewrap
make -C q2 clean
make -C q2 CC=gcc
sudo python3 judge/test_semester.py --assignment 4 --binary ./q2/langar --json result.json
python3 judge/check_submission.py ./submission
```

The structural checker expects an extracted submission containing `q2/`.
It checks required nonempty Q2 source/report files and the Q2 video MP4 header.
Build outputs must be removed before submission.

Functional scoring (100 total):

- `previous_features`: 20
- `cpu_affinity`: 20
- `address_space_limit`: 20
- `bounded_allocation`: 15
- `combined_controls`: 15
- `invalid_resource_options`: 10

Exit codes: 0 passed, 1 functional failures, 2 setup/environment error. The CLI
also uses 3 for build failure and 130 for interruption. Setup/build errors have
no functional score. Tests print each failure and write per-case JSON. Prior
features include the earlier milestones; HW8 deliberately moves the isolated
command from namespace PID 1 to a child of its PID-1 supervisor. The original
non-isolated HW2 contract remains unchanged.

Primary documentation: [Linux manual pages](https://man7.org/linux/man-pages/),
[OCI image spec v1.1.1](https://github.com/opencontainers/image-spec/tree/v1.1.1).
