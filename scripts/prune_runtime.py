"""Remove a fixed set of build/interactive tools inside the disposable image build.

Debian protects login for general-purpose systems. This single-purpose image uses
an existing numeric non-root identity and has no login service. The allow flag is
used only after verifying that no Essential package or unlisted removal is planned.
"""
import json
import os
import subprocess

REMOVE=frozenset({'apt','libapt-pkg7.0','mount','login','libncursesw6','adduser','passwd'})


def inventory():
    text=subprocess.check_output(['dpkg-query','-W','-f=${Package}|${Essential}|${db:Status-Status}\n'],text=True)
    return {name:{'essential':essential=='yes','installed':status=='installed'}
            for name,essential,status in (line.split('|') for line in text.splitlines())}


def validate_plan(text,packages):
    removals=set()
    for line in text.splitlines():
        fields=line.split()
        if fields and fields[0]=='Inst':raise ValueError('Runtime pruning must not install packages')
        if fields and fields[0] in ('Purg','Remv'):removals.add(fields[1])
    if removals!=REMOVE:raise ValueError('Unexpected package removal plan')
    if any(packages.get(name,{}).get('essential',True) for name in removals):
        raise ValueError('Essential package removal is forbidden')
    return sorted(removals)


def main():
    if os.geteuid()!=0:raise SystemExit('Image build root identity required')
    before=inventory()
    plan=subprocess.check_output(['apt-get','--simulate','purge',*sorted(REMOVE)],text=True)
    removals=validate_plan(plan,before)
    subprocess.run(['apt-get','--yes','--allow-remove-essential','purge',*removals],check=True)
    after=inventory()
    if any(after.get(name,{}).get('installed') for name in REMOVE):raise RuntimeError('Unused runtime package still installed')
    if any(p['essential'] and p['installed'] and not after.get(name,{}).get('installed') for name,p in before.items()):
        raise RuntimeError('Essential package unexpectedly removed')
    audit=subprocess.check_output(['dpkg','--audit'],text=True)
    if audit.strip():raise RuntimeError('Package database requires attention: '+audit)
    print(json.dumps({'removed_packages':removals,'essential_packages':'preserved','dpkg_audit':'clean'}))


if __name__=='__main__':main()
