#!/usr/bin/env python3
"""Observe process-creation, exec and wait syscalls without implementing a tracer."""
import re
from pathlib import Path
from common import main

def experiment(lab):
    lab.need('strace','sh')
    trace=lab.directory/'process.trace'
    lab.run(['strace','-f','-e','trace=process','-o',trace,
             '/bin/sh','-c','sleep 0.1 & wait'])
    text=trace.read_text();print(text,end='')
    lab.observations.append(dict(artifact='process.trace',content=text))
    # Linux/glibc may implement fork via clone/clone3 and waitpid via wait4.
    return dict(has_creation=bool(re.search(r'\b(fork|vfork|clone|clone3)\(',text)),
                has_exec='execve(' in text,has_wait=bool(re.search(r'\b(wait4|waitid|waitpid)\(',text)))
if __name__=='__main__':raise SystemExit(main(3,experiment))
