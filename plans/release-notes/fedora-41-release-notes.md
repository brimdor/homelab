# Fedora f41 Release Notes
*Auto-generated from upstream release notes*


---
## File: desktop.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For Desktop Users


### Proprietary nVidia graphics drivers are now available with UEFI Secure Boot support
Previously, nVidia driver installation had been removed from GNOME Software because it didn’t support Secure Boot, which is increasingly-often enabled by default, especially on laptops. This change brings the option back for Fedora Workstation users with Secure Boot supported. This is good news for those who want to use Fedora for gaming and CUDA. The change also helps Fedora stay relevant for AI/LLVM workloads.

When installing these drivers, you will be prompted to create a password for a key which will be used by the `mokutil` utility to authenticate the driver. After rebooting your system, you will be shown the `mokutil` interface which will ask you for the same password. Upon entering it, the driver installation will be completed and you will be able to proceed as normal, with nVidia drivers installed and enabled. The entire process is also explained in GNOME Software when installing these drivers.

For more information about `mokutil`, see [Fedora Quick Docs](https://docs.fedoraproject.org/en-US/quick-docs/mok-enrollment/).


### Fedora Miracle window manager & spin
This release introduces the Fedora Miracle Window Manager Spin. The Fedora Miracle Window Manager Spin aims to provide the premiere Miracle window manager experience on top of Fedora Linux, the leading edge platform for developers and users alike. 

The Miracle window manager is a tiling window manager based on the Mir compositor library. While it is a newer project, it contains many useful features such as a manual tiling algorithm, floating window manager support, support for many Wayland protocols, proprietary Nvidia driver support, and much more. Miracle will provide Fedora Linux with a high-quality Wayland experience built with support for all kinds of platforms, including low-end ARM and x86 devices. On top of this, Fedora Linux will be the first distribution to provide a Miracle-based spin, ensuring that it will become the de facto distribution for running Miracle. 

To try Miracle, install the `miracle-wm` package and select it at login, or install using the new spin available at link:++https://fedoraproject.org/++.


### IBus Chewing for Traditional Chinese (Taiwan) desktop by default
Fedora 41 changes the default input method for Traditional Chinese (Taiwan), the `zh_TW` locale, from `ibus-libzhuyin` to `ibus-chewing`. `ibus-chewing` is the ibus front-end of the `libchewing` library. Chewing (新酷音, link:++https://chewing.im/++) is one of the most popular and featureful IM among `zh_TW` users. 


### Workstation edition media are now Wayland only
Starting with Fedora 41, the Workstation edition install media only contain Wayland GNOME packages, and no X11 ones. X11 packages are still available in Fedora update repositories, but are no longer used on the installation media. If you perform a new installation and wish to use X11, install the `gnome-session-xsession` and `gnome-classic-session-xsession` packages, and select the X11 session during the next login.


### KDE Plasma Mobile spin
This release brings the Fedora KDE Plasma Mobile Spin and its corresponding Atomic variant: Kinoite Mobile. Built on the foundations of KDE Plasma Desktop, KDE Plasma Mobile and Kinoite Mobile bring its flexibility to a mobile form factor. Although originally geared towards phones, the touch friendly interface works very well on tablets and 2-in-1 laptops. 


### TaskWarrior 3
Fedora 41 provides version 3 of the TaskWarrior command line TODO list manager. Note that users of the previous version will have to migrate their lists manually; see the [upstream migration guide](https://taskwarrior.org/docs/upgrade-3/) for instructions.

A compatibility package named `task2` is also available for those who do not want to switch to version 3. Note that older versions are not being maintained by upstream.


### LXQt 2.0
The LXQt desktop environment in Fedora 41 has been upgraded to version 2.0, which is built on Qt 6 and adds experimental Wayland support.

For more information, see the [upstream release announcement](https://lxqt-project.org/release/2024/04/15/release-lxqt-2-0-0/).


### IPU6 Camera Support
Fedora 41 has added support for IPU6 cameras on laptops using ov2740, ov01a10 and hi556 sensors using the IPU6 CSI-receiver (isys) driver. This support requires using applications which support accessing cameras through `pipewire` such as Firefox. This change enables out-of-the-box support for cameras on some modern laptops which are directly attached to the CPU or SoC over a MIPI CSI2 data bus, instead of the more common USB UVC protocol.


### GIMP 3
This release of Fedora Linux updates GIMP, the GNU Image Manipulation Program, to major version 3, with many new features and improved user experience. Existing third party GIMP plugins for version 2 may not work with this new version. Note that the version packaged in Fedora 41 at release is a pre-release version (version 2.99), as upstream currently does not have a full release. It will be updated once upstream is ready.

GIMP 2 has been removed from Fedora due to its dependency on Python 2, which has also been removed in this release. If you wish to continue using GIMP 2, you can install it as a flatpak from [Flathub](https://flathub.org/apps/org.gimp.GIMP).

---
## File: developers.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For Developers


### Python 3.13
Fedora 41 provides Python 3.13, the latest major release of the Python language. For a list of changes in this release, see the [upstream documentation](https://docs.python.org/dev/whatsnew/3.13.html#what-s-new-in-python-3-13), especially the [Porting to Python 3.13](https://docs.python.org/dev/whatsnew/3.13.html#porting-to-python-3-13) section.

In addition, PythonC is now built with the `-03` compiler flag in Fedora, which aligns with how Python is built upstream, and provides a noticeable performance improvement (for example, 1.04x faster `pyperformance` geometric mean). This only affects the interpreter and standard Python library, not any third party extension modules built as RPMs or on developer systems.

#### Notes on migrating user-installed pip packages
When you upgrade from Fedora 40 to Fedora 41, the main Python interpreter version changes from 3.12 to 3.13.  If you have any Python packages installed using `pip`, you must complete the following procedure to migrate them to the new version:

. Install the previously main Python version:
+
[source,bash]
----
sudo dnf install python3.12
----

. Get `pip` for the previously main Python version:
+
[source,bash]
----
python3.12 -m ensurepip --user
----

. Observe the installed packages:
+
[source-bash]
----
python3.12 -m pip list
----

. Save the list with specific versions:
+
[source,bash]
----
python3.12 -m pip freeze > installed.txt
----

. Install the same packages for the now default version:
+
[source,bash]
----
python3 -m pip install --user -r installed.txt
----

. Uninstall user-installed packages for 3.12; this ensures proper removal of files in `~/.local/bin`:
+
[source,bash]
----
python3.12 -m pip uninstall $(python3.12 -m pip list --user --format freeze | cut -d= -f1)
----

. Optionally, clean up the now empty directory structure:
+
[source,bash]
----
rm -rf ~/.local/lib/python3.12/
----

. Optionally, remove the unneeded Python version:
+
[source,bash]
----
sudo dnf remove python3.12
----

Additionally, if you have any `pip` packages installed using `sudo`, run the following commands _before running the final step above which removes `python3.12`_, or install it again temporarily:

. Get `pip` for the previously main Python version for `root`:
+
[source,bash]
----
sudo python3.12 -m ensurepip
----

. Observe the system-installed packages:
+
[source,bash]
----
sudo python3.12 -m pip list
----

. Uninstall installed packages for 3.12; this ensures proper removal of files in `/usr/local/bin`:
+
[source,bash]
----
sudo python3.12 -m pip uninstall $(python3.12 -m pip list | cut -d" " -f1)
----

. Optionally, clean up now empty directory structure:
+
[source,bash]
----
sudo rm -rf /usr/local/lib*/python3.12/
----

[IMPORTANT]
====
If you followed the first procedure, the packages are already installed for your user account, which is the preferred option. Avoid using `sudo pip` in the future; these instructions are only intended to recover users who already used `sudo pip` in the past.
====


### Pytest 8

Pytest is a testing framework for Python-based projects. With Pytest you can write simple and scalable test cases for your code. Pytest 8 is now available, which removes a lot of deprecated functions and introduces some breaking changes. The notable updates include:

* Improved differences that `pytest` prints when assertion fails.
* The internal `FixtureManager.getfixtureclosure` method has changed. Plugins that use this method or that subclass the `FixtureManager` component and overwrite `FixtureManager.getfixtureclosure`, will need to adapt.
* The `new-style` hook wrappers are now used internally.
* Sanitized the handling of the default parameter when defining configuration options.
* [Some packages](https://fedoraproject.org/wiki/Changes/Pytest_8#Detailed_Description) will likely fail to build.

For more details, see the [upstream release notes](https://docs.pytest.org/en/stable/changelog.html).


### PyTorch 2.4
Fedora 41 provides PyTorch version 2.4, the latest upstream of this popular Python library for deep learning using CPUs and GPUs.

For more information, see the [upstream release announcement](https://pytorch.org/blog/pytorch2-4/) and [release notes](https://github.com/pytorch/pytorch/releases/tag/v2.4.0).


### ROCm 6.2
ROCm 6.2 is the latest iteration of AMD's compute libraries that work with the linux kernel to allow users to run compute workloads on their GPUs. As many GPU's as possible are enabled so open acceleration is available and easy for to as wide an audience as possible. It is also integrated with PyTorch in Fedora 41. See the [upstream release notes](https://rocm.docs.amd.com/en/docs-6.2.0/about/release-notes.html) for details.


### Python 2 retired
The `python2.7` package has been retired without replacement from Fedora Linux 41. There will be no Python 2 in Fedora 41 or later, other than PyPy. Packages requiring python2.7 on runtime or buildtime will have to be updated to use Python 3, or be retired as well. 


### Golang 1.23

The latest stable release of this programming language is now available in Fedora 41. Notable changes include:

* The `range` clause in the `for-range` loop accepts iterator functions as range expressions. The supported types of iterator functions are:
+
--
** func(func() bool)
** func(func(K) bool)
** func(func(K, V) bool)
--
+
Calls of the iterator argument function produce the iteration values for the `for-range` loop.

* The Go toolchain can collect usage and breakage statistics. These are referred to as "Go telemetry" and represent an opt-in-system controlled by the `go telemetry` command.

* The `GOROOT_FINAL` environment variable no longer works. Install a symbolic link instead of relocating or copying the `go` binary if your distribution installs the `go` command to a location other than `$GOROOT/bin/go`.

* The traceback message printed by the runtime after a fatal error now indents the second and subsequent lines of the message by a single tab.

* Significant changes to the implementation of the `time.Timer` and `time.Ticker` types.

For more details, see the [upstream release notes](https://tip.golang.org/doc/go1.23).



### Perl 5.40

The latest stable release of this programming language is now available in Fedora 41. Notable changes include:

* New `__CLASS__` keyword

* `:reader` attribute for field variables. This requests that an accessor method be automatically created that returns the value of the field variable from the given instance.

*  When processing command-line options, Perl allows a space between the `-M` switch and the name of the module after it.

* The `inf` and `nan` functions (experimental) have been added to the `builtin` namespace. They act as constants that yield the floating-point infinity and Not-a-Numer value respectively.

* Calling the `import` method of an unknown package produces a warning.

* The syntax of the `return` operator now rejects indirect objects.

* Using `goto` to jump from an outer scope into an inner scope is deprecated and will be removed completely in Perl 5.42.


For more details, see the [upstream release notes](https://perldoc.perl.org/perl5400delta).


### NodeJS 22.0

Fedora 41 now ships with Node.js 22.x as the default Node.js JavaScript server-side engine. If your applications are not yet ready for this newer version, they will need to be modified to depend on the compatibility package `nodejs20` and to rely on `/usr/bin/node20` instead of `/usr/bin/node` for operation. 


### Haskell GHC 9.6 and Stackage LTS 22

For Fedora 41, the main GHC Haskell compiler package have been from version 9.4.5 to the latest stable 9.6.6 release (rebasing the ghc package from the ghc9.6 package). Along with this, Haskell packages in Stackage (the stable Haskell source package distribution) have been updated from the versions in LTS 21 to latest LTS 22 release. Haskell packages not in Stackage have been updated to the latest appropriate version in the upstream Hackage package repository. 

For full information about this release, see the [upstream release notes](https://downloads.haskell.org/~ghc/9.6.6/docs/users_guide/9.6.1-notes.html) and [migration guide](https://gitlab.haskell.org/ghc/ghc/-/wikis/migration/9.6).


### GNU Toolchain update
The GNU toolchain in Fedora 41 has been updated to:

* GNU C Compiler (`gcc`) 14.1+ 
* GNU Binary Utilities (`binutils`) 2.42+
* GNU C Library (`glibc`) 2.40
* GNU Debugger (`gdb`) 14+

Also see the upstream release notes for [GCC](https://gcc.gnu.org/gcc-14/changes.html), [Binutils](https://lists.gnu.org/archive/html/info-gnu/2024-01/msg00016.html), [GLibC NEWS](https://sourceware.org/git/?p=glibc.git;a=blob;f=NEWS;hb=HEAD), and [GDB NEWS](https://www.sourceware.org/gdb/news/).


### LLVM 19
LLVM sub-projects in Fedora have been updated to version 19.

Compatibility packages `clang18`, `llvm18`, `lld18`, `compiler-rt18`, and `libomp18` have been added to ensure that packages that currently depend on clang and llvm version 18 libraries will continue to work. Previous compatibility packages present in Fedora 40, such as `llvm17`, `clang17`, etc. have been retired.

See the [LLVM 19 Release Notes](https://releases.llvm.org/19.1.0/docs/ReleaseNotes.html) for additional information about this release.

---
## File: feedback.adoc


include::partial$entities.adoc[]


## Feedback

Thank you for taking the time to provide your comments, suggestions, and bug reports to the Fedora community; this helps improve the state of Fedora, Linux, and free software worldwide.

### Providing Feedback on Fedora Software

To provide feedback on Fedora software or other system elements, please refer to [Bugs And Feature Requests](https://docs.fedoraproject.org/en-US/quick-docs/bugzilla-file-a-bug/). A list of commonly reported bugs and known issues for this release is available from [Common Bugs]({COMMONBUGS_URL}) on the forums.

### Providing Feedback on Release Notes

If you feel these release notes could be improved in any way, you can provide your feedback directly to the beat writers. There are several ways to provide feedback, in order of preference:

* Open an issue at []({BZURL}) - *This link is ONLY for feedback on the release notes themselves.* Refer to the admonition above for details.

* E-mail the Release-Note mailing list at [relnotes@fedoraproject.org](mailto:relnotes@fedoraproject.org).

---
## File: hardware_overview.adoc

include::partial$entities.adoc[]


## Hardware Overview

Fedora {PRODVER} provides software to suit a wide variety of applications. The storage, memory and processing requirements vary depending on usage. For example, a high traffic database server requires much more memory and storage than a business desktop, which in turn has higher requirements than a single-purpose virtual machine.


### Minimum System Configuration

The figures below are a recommended minimum for the default installation. Your requirements may differ, and most applications will benefit from more than the minimum resources.

* 2GHz dual core processor or faster

* 2GB System Memory

* 15GB unallocated drive space

Users of system equipped with the minimum memory of 2GB may want to consider Fedora Spins with less resource intense Desktop Environments

.Low memory installations
[NOTE]
====
Fedora {PRODVER} can be installed and used on systems with limited resources for some applications. Text, VNC, or kickstart installations are advised over graphical installation for systems with very low memory. Larger package sets require more memory during installation, so users with less than 768MB of system memory may have better results performing a minimal install and adding to it afterward.

For best results on systems with less than 1GB of memory, use the DVD installation image.
====
### Recommended System Configuration

The figures below are recommended for the default x86_64 Workstation installation featuring the Gnome desktop . Your requirements may differ, depending on Desktop Environment and use case.

* 2GHz quad core processor

* 4GB System Memory

* 20GB unallocated drive space

.Low memory installations
[NOTE]
====
Fedora {PRODVER} can be installed and used on systems with limited resources for some applications. Text, VNC, or kickstart installations are advised over graphical installation for systems with very low memory. Larger package sets require more memory during installation, so users with less than 768MB of system memory may have better results preforming a minimal install and adding to it afterward.

For best results on systems with less than 1GB of memory, use the DVD installation image.
====


### Display resolution

VGA capable of 1024x768 screen resolution

.Graphical Installation requires 800x600 resolution or higher
[NOTE]
====
Graphical installation of Fedora requires a minimum screen resolution of 800x600. Owners of devices with lower resolution, such as some netbooks, should use text or VNC installation.

Once installed, Fedora will support these lower resolution devices. The minimum resolution requirement applies only to graphical installation.
====


### Graphics Hardware


#### Minimum Hardware for Accelerated Desktops

Fedora {PRODVER} supports most display adapters. Modern, feature-rich desktop environments like *GNOME* and *KDE Plasma Workspaces* use video devices to provide 3D-accelerated desktops. Older graphics hardware may *not support* acceleration:

* Intel prior to GMA9xx

* NVIDIA prior to NV30 (GeForce FX5xxx series)

* Radeon prior to R300 (Radeon 9500)


#### CPU Accelerated Graphics

Systems with older or no graphics acceleration devices can have accelerated desktop environments using *LLVMpipe* technology, which uses the CPU to render graphics. *LLVMpipe* requires a processor with `SSE2` extensions. The extensions supported by your processor are listed in the `flags:` section of `/proc/cpuinfo`


#### Choosing a Desktop Environment for your hardware

Fedora {PRODVER}'s default desktop environment, *GNOME*, functions best with hardware acceleration. Alternative desktops are recommended for users with older graphics hardware or those seeing insufficient performance with *LLVMpipe*.

Desktop environments can be added to an existing installation and selected at login. To list the available desktops, use the [command]`dnf environment list` command:

----
# dnf environment list
----

Install the desired environment using its ID as listed in the above command's output:

----
# dnf install @cinnamon-desktop-environment
----

For more information, see the `dnf5-environment` man page.

---
## File: index.adoc

include::partial$entities.adoc[]

## Release Notes

Release Notes for Fedora Linux {PRODVER}

[abstract]
--
This document provides the release notes for Fedora Linux {PRODVER}. It describes major changes offered as compared to Fedora Linux {PREVVER}.
// Fedora Linux {PRODVER} was released on YYYY-MM-DD.
--

[TIP]
====
Have something that should be included in the release notes?
Notice something wrong?
File an issue in the https://gitlab.com/fedora/docs/fedora-linux-documentation/release-notes/-/issues[Release Notes repository].
====

[NOTE]
====
Use the sidebar on the left to navigate the Release Notes as well as other documentation for Fedora {PRODVER}.
====

image:title_logo.svg[Fedora Logo]
include::partial$Legal_Notice.adoc[]

---
## File: sysadmin.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For System Administrators


### Installation release notes
Release notes for matters related to the installation of Fedora 41 - the Anaconda installer, kickstart, etc., can be found in the [upstream Release Notes](https://anaconda-installer.readthedocs.io/en/latest/release-notes.html#fedora-41) on Readthedocs.


### Self-encrypting drives support in the installer
Starting with Fedora 41, the Anaconda installer has built-in support for self-encrypting hard drives - that is, native hardware encryption on TCG OPAL2 compliant drives.

For more information, see the upstream [Cryptsetup release notes](https://cdn.kernel.org/pub/linux/utils/cryptsetup/v2.7/v2.7.0-ReleaseNotes).


### DNF 5
The default package manager in Fedora 41 is DNF 5. This is a large upgrade that brings many enhancements, notably:

* **Reduced footprint**: The dnf5 package is a fully-featured package manager that doesn't require Python dependencies. It also reduces the number of software management tools in Fedora by replacing both the dnf and microdnf packages. The installation size of the `dnf5` stack in an empty container is approximately 60% smaller than the dnf installation.
+
Additionally, in previous Fedora releases, `dnf`, `microdnf`, and `PackageKit` used their own caches, leading to significant metadata redundancy. With `dnf5` and `dnf5daemon`, which share metadata, this redundancy will be eliminated. 
* **Faster query processing**: The processing of package metadata is now significantly faster. Executing commands such as `repoquery` to list packages available in repositories is now twice as fast compared to `dnf`. Similarly, operations like listing dependencies or parsing numerous command-line arguments are notably expedited, potentially saving users seconds to tens of seconds in waiting time for the results. 
* **Lowered maintenance costs**: Many functional duplicates in dnf were eliminated during the development of the new `dnf5` package manager. This was partly because the integration of the original `PackageKit` and `dnf` libraries into the original `libdnf` library was never completed. Plugins are now included in the same package as the core functionality. 
* **Consolidated and streamlined API**: The API for managing packages, working with repositories, and solving package dependencies is now consolidated into a single component, providing a unified solution. The original dnf API underwent a review process, during which unused workflows and obsolete methods were removed, while improving usability for users. 
* **Enhanced command-line outputs**: Transaction tables now offer more detailed information, verbose scriptlet outputs are redirected and organized by package name into log files, individual commands come with their own man pages, bash completion has been enhanced, and numerous other improvements have been made. 
* **Unified user experience**: Consistent user experience is now offered to users across servers, workstations, and containers, as `dnf5` is the sole package manager deployed there. Existing `dnf`, `yum`, and `microdnf` commands are linked to `dnf5`, while compatibility aliases for essential use cases will be provided to facilitate migration. Configuration files are now shared among `dnf5` components. API users will encounter unified code style and naming conventions. Various scripting language interfaces are now provided from a single source using SWIG bindings (formerly CPython and SWIG). 

For information about this release, see the [upstream DNF5 documentation](https://dnf5.readthedocs.io/en/latest/), particularly the [list of changes between DNF and DNF5](https://dnf5.readthedocs.io/en/latest/changes_from_dnf4.7.html). Developers should also check the [DBus API bindings for dnfdaemon](https://dnf5.readthedocs.io/en/latest/dnf_daemon/dnf5daemon_dbus_api.8.html).


### RPM 4.20
RPM in Fedora 41 has been updated to version 4.20, which provides a number of improvements, such as:

* Hands-free packaging 
** Declarative build system
** Dynamic spec generation extended
** File trigger scriptlet arguments
** Support for spec local dependency generators
** Support for sysusers 'm' directive
** Guaranteed per-build directory
* Public plugin API
* Increased install scriptlet isolation

See the [upstream release notes](https://rpm.org/wiki/Releases/4.20.0) for details.


### DNF and bootc in Image Mode Fedora variants
Starting with Fedora 41, the Fedora Atomic Desktops, Fedora CoreOS and Fedora IOT will ship `bootc` and DNF5 as part of the image. Now you can use `dnf` commands as part of container builds that use these Fedora variants as the base image. While `rpm-ostree` is still available, you can now use `bootc` to manage your image mode deployments and updates.

When running dnf on a booted image mode system, DNF will give a better error message pointing to the available tools on your booted system to accomplish your task. This is the start of a process to enable DNF with `rpm-ostree` features and the re-focus on `bootc` to manage image mode deployments. 


### SPDX Migration

RPM packages use SPDX identifiers as a standard for licenses. 90 % of the packages have been migrated to [SPDX identifiers](https://spdx.org/licenses/). The remaining packages are estimated to be migrated to SPDX in Fedora 42. A list of all licenses allowed (and used) in Fedora Linux can be found at [Fedora Legal page](https://docs.fedoraproject.org/en-US/legal/all-allowed/). Out of 90%, nine percent of the packages have a temporary license `LicenseRef-Callaway-*` that conforms to SPDX, but needs to be assigned the correct license ID from the SPDX organization.


### Remove ifcfg support in NetworkManager

NetworkManager removes support for connection profiles stored in ifcfg format. It is deprecated upstream and the native Keyfile format is valid and a better replacement. The following packages are being dropped. `NetworkManager-initscripts-ifcfg-rh`, `NetworkManager-dispatcher-routing-rules` and `NetworkManager-initscripts-updown`.


### Running SSSD with reduced privileges

To support general system hardening (running software with least privileges possible), the SSSD service is now configured to run under `sssd` or `root` user using the `systemd` service configuration files. This service user now defaults to `sssd` and irrespective of what service user is configured, `root` or `sssd`, all root capabilities are dropped with the exception of a few privileged helper processes.

### Removal of the `sss_ssh_knownhostsproxy` tool

The `sss_ssh_knownhostsproxy` tool was deprecated in the previous release and has now been removed. It is replaced by the `sss_ssh_knownhosts` tool. See `man sss_ssh_knownhosts(1)` to learn how to use it.


### Consistent device naming in Fedora Cloud

Previously, the Fedora Cloud edition used to set the `net.ifnames=0` kernel command-line parameter during the kickstart process. This would disable the consistent naming for networking devices and ensured that Ethernet devices kept their traditional names such as `eth0`, `eth1`, and so on. With this update, `net.ifnames=0` has been removed from the Fedora Cloud kickstart file to ensure consistency in the network device naming and to align with the other Fedora editions.


### Remove `network-scripts`

With this update, the long-deprecated package `network-scripts` will be removed. The package provided the legacy utilities `ifup` and `ifdown`, as well as the `network.service`. Network scripts heavily depend on the Dynamic Host Configuration Protocol (DHCP) client, and without active development, there is no chance of updating them to use an alternative client.

Packages that depend to some extent on `network-scripts`:

* [libteam](https://bugzilla.redhat.com/show_bug.cgi?id=2262986)
* [NetworkManager](https://bugzilla.redhat.com/show_bug.cgi?id=2275295)
* [openvswitch](https://bugzilla.redhat.com/show_bug.cgi?id=2262982)
* [ppp](https://bugzilla.redhat.com/show_bug.cgi?id=2262981)

Note that this change also affects all users with local custom network-scripts that require functionality from the `network-scripts` package.


### Access to all versions of Kubernetes and its related components

Starting with Fedora 41, all supported versions of Kubernetes, CRI-O and CRI-Tools will be available concurrently. As an example, Fedora 41 has the following Kubernetes RPMs at release: 

* `kubernetes1.29`
* `kubernetes1.30`
* `kubernetes1.31`

This is a significant change from the past Fedora releases, which only had a single version of Kubernetes available in Fedora repositories. CRI-O and CRI-Tools RPMs also share this change with versions available to complement Kubernetes. For more information, see this [Fedora Quick Doc](https://docs.fedoraproject.org/en-US/quick-docs/using-kubernetes/).


### TuneD is the default power profile management {docdir}

TuneD replaced `power-profiles-daemon` as a default power profile management daemon for the following Fedora workstation spins:

* KDE Plasma
* GNOME

The server users can customize the desktop-exposed power profiles by editing the `/etc/tuned/ppd.conf` file in the command-line. The workstation users can set the power profile through the GUI control center.

The `tuned-ppd` package provides a drop-in replacement for the `power-profiles-daemon`, which allows it to be used with the current desktops.

Those applications that already use `power-profiles-daemon` can access TuneD without modifying the code.


### Netavark uses `nftables` by default

Netavark is a container networking tool used by Podman. Netavark manages interfaces and firewall rules and with this Fedora update, it will use `nftables` by default to create firewall rules for containers.


### Unprivileged updates for Fedora Atomic Desktops

On Atomic Desktops, the policy controlling access to the `rpm-ostree` daemon has been updated to:

* Enable users to update the system without having elevated privileges or typing a password. Note that this change only applies to system updates and repository meta updates; not to other operations.

* Reduce access to the most privileged operations (such as changing the kernel arguments, or rebasing to another image) of `rpm-ostree` for administrators to avoid mistakes. Only the following operations will remain password-less to match the behavior of the package mode Fedora with the `dnf` command:
** install and uninstall packages
** upgrade the image
** rollback the image
** cancel transactions
** cleanup deployment


### ComposeFS enabled by default for Fedora CoreOS and IoT editions

On Fedora CoreOS and Fedora IoT systems, the root mount of the system (`/`) is now mounted using `composefs`, which makes it a truly read only filesystem, increasing the system integrity and robustness. This is the first step toward a full at runtime verification of filesystem integrity.


### Enable bootupd on Fedora Silverblue and Kinoite editions
On Atomic Desktops, the bootloader is now automatically updated using `bootupd`. New systems are now installed with a static GRUB configuration which relies only on the Boot Loader Specification configuration files and is not regenerated for each update.


### Multiple versioned Kubernetes packages
The upstream Kubernetes project maintains 3 concurrent versions with a new release every 4 months. Previously, in Fedora, only one of these versions was always provided, and matched with a specific release. Starting with Fedora 41, all currently supported Kubernetes versions are provided, using separate packages named after each major version. Using the `kubernetes-client` rpm as an example, instead of `kubernetes-client-1.29.2-1.fc41`, Fedora now offers `kubernetes1.29-client-1.29.2-1.fc41`, `kubernetes1.28-client-1.28.5-1.fc41`, and `kubernetes1.27-client-1.27.8-1.fc41`.

Upgrading to Fedora 41 on a machine with Fedora 40 or Fedora 39 requires a manual step by the user to select the appropriate versioned Kubernetes package.

For more information, see the [Fedora Quick Docs](https://docs.fedoraproject.org/en-US/quick-docs/using-kubernetes-versioned/).


### dm-vdo and vdo-8.3
Fedora 41 is the first Fedora release that provides the `dm-vdo` (virtual data optimizer) device mapper target, along with the `vdo` user tools package.

The `dm-vdo` target provides inline deduplication, compression, and thin provisioning. These features can be added to the storage stack, compatible with any file system. A `dm-vdo` target can be backed by up to 256TB of storage, and can present a logical size of up to 4PB. This target was originally developed starting in 2009. It was first released in 2013, and has been used in production environments ever since. It was made open-source in 2017, and merged into the upstream Linux kernel in 2024.

To support `dm-vdo` targets, the `vdo` user tool package provides the following tools:

* `vdoformat`, which is required to create and format vdo volumes.
* `vdostats`, which displays useful configuration and statistics information for vdo volumes.
* `vdoforcerebuild`, which is used in bringing a vdo out of read-only mode following an unrecoverable error.

Additional diagnostic tools are also included in the `vdo` package. However, they are rarely needed for normal operation.

Although not required, it is strongly recommended that `lvm2` be used to manage vdo volumes. See the `lvm2` documentation for more information. 

If you have a vdo volume created with the kvdo module, be sure to refer to the [kvdo documentation](https://github.com/dm-vdo/kvdo) for important considerations prior to attempting to upgrade to a `dm-vdo` target.

See the [dm-vdo](https://github.com/dm-vdo/vdo-devel) and [vdo](https://github.com/dm-vdo/vdo) upstream documentation for additional details.


### Stratis 3.7: stratisd 3.7.3 and stratis-cli 3.7.0
This update includes releases of `stratisd` 3.7.3 and `stratis-cli` 3.7.0. It includes one significant enhancement, several minor enhancements, and a number of small improvements.

Most significantly, Stratis 3.7.3 extends its functionality to allow a user to revert a snapshot, i.e., to overwrite a Stratis filesystem with a previously taken snapshot of that filesystem. The process of reverting
requires two steps. First, a snapshot must be scheduled for revert. However, the revert can only take place when a pool is started. This can be done while `stratisd` is running, by stopping and then restarting the pool. A revert may also be occasioned by a reboot of the system stratisd is running on. Restarting stratisd will also cause a scheduled revert to occur, so long as the pool containing the filesystem to be reverted has already been stopped. To support this functionality, `stratis-cli` includes two new filesystem subcommands, `schedule-revert` and `cancel-revert`.

Some additional functionality has been added to support this revert functionality. First, a filesystem's origin field is now included among its D-Bus properties and updated as appropriate. `stratis-cli` displays an origin value in its newly introduced filesystem detail view. `stratisd` also support a new filesystem D-Bus method which returns the filesystem metadata. The filesystem debug commands in `stratis-cli` now include a get-metadata option which will display the filesystem metadata for a given pool or filesystem. Equivalent functionality has been introduced for the pool metadata as well.

`stratisd` also includes a considerable number of dependency version bumps, minor fixes and additional testing, while `stratis-cli` includes improvements to its command-line parsing implementation.

Please consult the [stratisd](https://github.com/stratis-storage/stratisd/blob/rebase-3.6.0/CHANGES.txt) and [stratis-cli](https://github.com/stratis-storage/stratis-cli/blob/rebase-3.6.0/CHANGES.txt) changelogs for additional information about the release.


### Fedora repoquery tool
Fedora 41 provides a new tool for querying repositories, `fedora-repoquery`, a small commandline tool for doing repoqueries of Fedora, EPEL, eln, and Centos Stream package repositories. It wraps dnf repoquery separating cached repo data under separate repo names for faster cached querying.

See the [upstream readme](https://github.com/juhp/fedora-repoquery#readme) for usage examples, or use `fedora-repoquery --help` after installing.


### OpenSSL now distrusts SHA-1 signatures by default
OpenSSL in Fedora 41 no longer trusts SHA-1 signatures by default and blocks their creation as well. This change was implemented because chosen-prefix collision attacks on SHA-1 are becoming increasingly feasible. This brings Fedora's security defaults closer to what is considered secure in modern day cryptographic landscape.

You can revert to previous default behavior either system-wide by using `update-crypto-policies --set FEDORA40`, or per process with `runcp FEDORA40 command args`, using the `crypto-policies-extra` tool available [Copr](https://copr.fedorainfracloud.org/coprs/asosedkin/crypto-policies-extras). These old policies will be maintained in Fedora for several future releases. However, their use is generally not recommended.


### Reproducible Package Builds
Fedora package builds are now more deterministic, bringing the distribution closer to the goal of achieving fully reproducible builds for all of its packages. 

For more information, see [Fedora's Reproducible Builds documentation](https://docs.fedoraproject.org/en-US/reproducible-builds/).


### Libvirt Virtual Network NFTables
The libvirt virtual network has been changed to prefer use of the `nftables` firewall backend instead of `iptables`.

This change has some potential compatibility impact; see the [Change page](https://fedoraproject.org/wiki/Changes/LibvirtVirtualNetworkNFTables#Upgrade/compatibility_impact++) for details and workarounds.


### Redis has been replaced with Valkey
Redis has been replaced with Valkey in Fedora 41 due to Redis' license change to RASLv2/SSPL which rendered it incompatible with Free and Open Source principles. Valkey is a full replacement of Redis which preserves the original BSD licensing.

When upgrading to Fedora Linux 41, systems with `redis` installed will be switched to `valkey` via the `valkey-compat` package. The change should be mostly transparent to users as the `valkey-compat` package provides config and data migration for most common configurations. The `valkey` systemd units will have aliases for `redis` to ease the migration for users. 


### OpenSSL engine support deprecated
Support for OpenSSL engines is deprecated in Fedora 41. Engines are not FIPS compatible and corresponding API is deprecated since OpenSSL 3.0. Those currently using OpenSSL engines should switch to using providers. 

---
## File: welcome.adoc

include::partial$entities.adoc[]


## Welcome to Fedora

The Fedora Project is a partnership of free software community members from around the globe. The Fedora Project builds open source software communities and produces a Linux distribution called Fedora.

The Fedora Project's mission is to lead the advancement of free and open source software and content as a collaborative community. The three elements of this mission are clear:

* The Fedora Project always strives to lead, not follow.

* The Fedora Project consistently seeks to create, improve, and spread free/libre code and content.

* The Fedora Project succeeds through shared action on the part of many people throughout our community.

To find out more general information about Fedora, refer to the following pages, on the Fedora Project Wiki:

* [Fedora Overview](https://fedoraproject.org/wiki/Overview)

* [Fedora FAQ](https://fedoraproject.org/wiki/FAQ)

* [Help and Discussions](https://fedoraproject.org/wiki/Communicate)

* [Participate in the Fedora Project](https://fedoraproject.org/wiki/Join)


### Need Help?

There are a number of places you can get assistance should you run into problems.

If you run into a problem and would like some assistance, go to [](https://ask.fedoraproject.org). Many answers are already there, but if you don't find yours, you can simply post a new question. This has the advantage that anyone else with the same problem can find the answer, too.

You may also find assistance on the `#fedora` channel on the IRC network `irc.libera.chat`. Keep in mind that the channel is populated by volunteers wanting to help, but folks knowledgeable about a specific topic might not always be available.


### Want to Contribute?

You can help the Fedora Project community continue to improve Fedora if you file bug reports and enhancement requests. Refer to [Bugs And Feature Requests](https://fedoraproject.org/wiki/BugsAndFeatureRequests) on the Fedora Wiki for more information about bug and feature reporting. Thank you for your participation.
