#!/usr/bin/python3 -I
"""Keep OCI instance-identity credentials inaccessible to worker/updater users."""
import os
import subprocess

if os.geteuid() != 0:
    raise SystemExit('Install and run the metadata guard as root')
for binary,address in [('/usr/sbin/iptables','169.254.169.254/32'),
                       ('/usr/sbin/ip6tables','fd00:c1::a9fe:a9fe/128')]:
    rule=['-d',address,'-p','tcp','--dport','80','-m','owner','!','--uid-owner','0',
          '-m','comment','--comment','DaniLabs root-only OCI identity','-j','REJECT']
    if subprocess.run([binary,'--wait','-C','OUTPUT',*rule],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        subprocess.run([binary,'--wait','-I','OUTPUT','1',*rule],check=True)
