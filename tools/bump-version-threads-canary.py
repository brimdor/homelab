#!/usr/bin/env python3
import sys
import re
import argparse
import datetime

def bump_version(file_path, bump_type, pre_release=None, set_version=None):
    with open(file_path, 'r') as f:
        content = f.read()

    if set_version:
        new_version = set_version
    else:
        match = re.search(r'version: (\d+\.\d+\.\d+)', content)
        if not match:
            print(f"Version not found in {file_path}")
            sys.exit(1)
        
        current_version = match.group(1)
        major, minor, patch = map(int, current_version.split('.'))

        if bump_type == 'major':
            major += 1
            minor = 0
            patch = 0
        elif bump_type == 'minor':
            minor += 1
            patch = 0
        elif bump_type == 'patch':
            patch += 1
        
        new_version = f"{major}.{minor}.{patch}"

    # Handle pre-release (rc.N)
    if pre_release:
        # If we are already on an rc, increment it
        # This is simple: we just append it or replace it.
        # The spec says: "If v1.0.3-rc.1 was already deployed and a new fix is needed, canary becomes v1.0.3-rc.2"
        # Since we are updating Chart.yaml which usually has the clean version, 
        # we will store the full version string there for canary.
        
        # Check if content already has -rc.N
        rc_match = re.search(r'version: (\d+\.\d+\.\d+)-rc\.(\d+)', content)
        if rc_match:
            base_version = rc_match.group(1)
            rc_num = int(rc_match.group(2)) + 1
            new_version = f"{base_version}-rc.{rc_num}"
        else:
            # Append .rc.1 to the newly calculated base version
            new_version = f"{new_version}-rc.1"

    content = re.sub(r'version: \d+\.\d+\.\d+(-rc\.\d+)?', f'version: {new_version}', content)
    
    with open(file_path, 'w') as f:
        f.write(content)
    
    return new_version

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bump', choices=['major', 'minor', 'patch'], help='Bump type')
    parser.add_argument('--set', help='Set version explicitly')
    parser.add_argument('--pre-release', action='store_true', help='Set as rc')
    parser.add_argument('--dry-run', action='store_true', help='Dry run')
    args = parser.parse_args()

    file_path = 'apps/threads-canary/Chart.yaml'
    
    if args.dry_run:
        print(f"Dry run: would bump {file_path}")
        return

    new_v = bump_version(file_path, args.bump, pre_release=args.pre_release, set_version=args.set)
    print(f"Version bumped to {new_v}")

if __name__ == '__main__':
    main()
