# Fedora f40 Release Notes
*Auto-generated from upstream release notes*


---
## File: desktop.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For Desktop Users


### KDE Plasma 6
Fedora 40 provides the KDE Plasma 6 desktop environment, a major upgrade from the previous version.

The new release provides a host of major changes, including partial HDR support, a new Overview effect, a floating panel, and many others. Also, The Cube is back.

KDE Plasma 6 is successor to KDE Plasma 5 created by the KDE Community. It is based on Qt 6 and KDE Frameworks 6 and brings many changes and improvements over previous versions. For Fedora Linux, the transition to KDE Plasma 6 will also include dropping support for the X11 session entirely, leaving only Plasma Wayland as the sole offered desktop mode. X11 applications are still supported, however. See the Feedback section on the [Change page](https://fedoraproject.org/wiki/Changes/KDE_Plasma_6#Feedback) for details.

For full information about the new KDE release, see the [official announcement](https://kde.org/announcements/megarelease/6/).


### IBus changes
The IBus package, which provides multilingual input in Fedora, has been updated to version 1.5.30. Enhancements include:

* The `ibus start` and `ibus restart` commands will work for KDE Plasma on Wayland. (They have worked previously in Plasma on X11.)
* The "Preference" menu item will be shown in IBus activate menu in Plasma on Wayland. (The change is not needed in Plasma on X11 since the context menu is also available.)

Additionally, the updated `ibus-anthy` package now updates the Japanese Era for 2024 for those using a Japanese locale.

---
## File: developers.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For Developers


### PyTorch
Fedora 40 is the first Fedora release that provides PyTorch, a machine learning framework based on the Torch library, used for applications such as computer vision and natural language processing, originally developed by Meta AI and now part of the Linux Foundation umbrella. It is free and open-source software released under the modified BSD license.

Providing PyTorch as a Fedora package means that users can now use DNF to install instead of pip. The initial version provided in Fedora 40 is 2.1.2. To install, run `dnf install python-torch`.

To get started with PyTorch, see the [official documentation](https://pytorch.org/docs/stable/index.html). Those specifically interested in PyTorch in Fedora - developers, packagers, end-users, and so on - may join the [PyTorch Fedora Special Interest Group](https://fedoraproject.org/wiki/SIGs/PyTorch).


### PHP 8.3

The stack for the PHP programming language interpreter has been upgraded to version 8.3, which provides multiple bug fixes and enhancements. Notable changes include:

* Explicit typing of class constants
* Dynamic class constant fetch
* New `#[\Override]` attribute
* Deep-cloning of readonly properties
* New `json_validate()` function
* New `Randomizer::getBytesFromString()` method
* Command line linter supports multiple files

For full extent of updates, see the [upstream release notes](https://www.php.net/releases/8.3/en.php).


### Golang 1.22
Fedora 40 provides Golang version 1.22. See the [upstream release notes](https://tip.golang.org/doc/go1.22) for a complete list of changes.


### Retire Python 3.7
Starting with this release, Python version 3.7 is considered retired without replacement due to being considered End of Life since June 2023.


### LLVM 18
All LLVM sub-projects have been updated to version 18, which includes a soname version change for llvm libraries. Compatibility packages clang17, llvm17, and lld17 have been added to ensure that packages that currently depend on clang and llvm version 17 libraries will continue to work.

Other notable changes include:

* clang will emit DWARF-5 by default instead of DWARF-4. This matches the upstream default. Fedora has been using DWARF-4 as the default for the last few releases due to https://bugzilla.redhat.com/show_bug.cgi?id=2064052.
* The compatibility packages will now include the same content as the main package. In previous releases, the compatibility packages contained only libraries and headers, and the binaries and other content was stripped out. These packages will be supported for use as dependencies for other RPM packages, but not for general purpose usage by end users. Fedora users should use Clang/LLVM 18.
* The compatibility packages added for Fedora 40 will be retired prior to the Fedora 41 branch.
* We will be enabling Fat LTO in redhat-rpm-config if this feature is complete in time for the upstream LLVM 18 release. Fat LTO is a feature that allows the compiler to produce libraries that contain LTO bitcode along side the traditional ELF binary code so that the libraries can be linked in both LTO mode and non-LTO mode. gcc also supports this feature and has it enabled in Fedora. In Fedora 39 and older, with LTO enabled, clang produces binaries with only LTO bitcode, so we need to run a post-processing script (brp-llvm-compile-to-elf) on the libraries to convert them to ELF code so they can be used by other packages. Enabling Fat LTO allows Fedora Project to remove this script and simplify the build process.

See the [upstream release notes](https://releases.llvm.org/18.1.0/docs/ReleaseNotes.html) for details.


### GNU toolchain updates
The GNU Compiler Collection, GNU Binary Utilities, GNU C Library, and the GNU Debugger make up the core part of the GNU Toolchain and it is useful for our users to transition these components as a complete implementation when making a new release of Fedora. 

Components of the GNU Toolchain (gcc, glibc, binutils, gdb) have been updated to the following versions in Fedora 40:

* gcc version 14.0 ([release notes](https://gcc.gnu.org/gcc-14/changes.html))
* binutils version 2.41 ([release notes](https://sourceware.org/pipermail/binutils/2023-July/128719.html))
* glibc 2.39 ([release notes](https://sourceware.org/git/?p=glibc.git;a=blob;f=NEWS;hb=HEAD))
* gdb 14.1 ([release notes](https://lists.gnu.org/archive/html/info-gnu/2023-12/msg00001.html))


### Boost 1.83
Fedora 40 includes Boost 1.83. For more information, see the [upstream release notes](https://www.boost.org/users/history/version_1_83_0.html).


### Ruby 3.3
The Ruby language has been updated to version 3.3 in Fedora 40, up from version 3.2 provided in the previous Fedora release. The new version adds a new parser called Prism, uses Lrama as a parser generator, adds a new pure-Ruby JIT compiler called RJIT, and provides many performance improvements, especially YJIT.

For full details, see the [upstream NEWS](https://github.com/ruby/ruby/blob/ruby_3_3/NEWS.md) and the [release announcement](https://www.ruby-lang.org/en/news/2023/12/25/ruby-3-3-0-released/).


### java-21-openjdk as the system JDK
The system JDK has been updated from version 17 to version 21 in Fedora 40. 

For more information about Java 21, see the [JDK 21 release notes](https://www.oracle.com/java/technologies/javase/21-relnote-issues.html), and the [migration guide](https://docs.oracle.com/en/java/javase/21/migrate/index.html).

Also see the [Change page](https://fedoraproject.org/wiki/Changes/Java21#Documentation) for a quick FAQ about this change.


### Retire Pipenv
Starting with this release, pipenv is no more packaged in Fedora and obsoleted, thus it might be removed during the upgrade process.

Developers in need of still using pipenv can install it directly from pip with `pip install --user pipenv`.

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

Fedora {PRODVER} supports most display adapters. Modern, feature-rich desktop environments like *GNOME3* and *KDE Plasma Workspaces* use video devices to provide 3D-accelerated desktops. Older graphics hardware may *not support* acceleration:

* Intel prior to GMA9xx

* NVIDIA prior to NV30 (GeForce FX5xxx series)

* Radeon prior to R300 (Radeon 9500)


#### CPU Accelerated Graphics

Systems with older or no graphics acceleration devices can have accelerated desktop environments using *LLVMpipe* technology, which uses the CPU to render graphics. *LLVMpipe* requires a processor with `SSE2` extensions. The extensions supported by your processor are listed in the `flags:` section of `/proc/cpuinfo`


#### Choosing a Desktop Environment for your hardware

Fedora {PRODVER}'s default desktop environment, *GNOME3*, functions best with hardware acceleration. Alternative desktops are recommended for users with older graphics hardware or those seeing insufficient performance with *LLVMpipe*.

Desktop environments can be added to an existing installation and selected at login. To list the available desktops, use the [command]`dnf grouplist` command:

----
# dnf grouplist -v hidden | grep Desktop
----

Install the desired group:

----
# dnf groupinstall "KDE Plasma Workspaces"
----

Or, use the short group name to install:

----
# dnf install @mate-desktop-environment
----

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


### Installer changes
For a list of changes in Fedora's Anaconda installer and related components such as Kickstart, see the [upstream release notes](https://anaconda-installer.readthedocs.io/en/latest/release-notes.html#fedora-40).


### Fedora IoT Bootable Container
There is now a bootable image available for Fedora IoT edition. This provides new means for users to consume Fedora IoT, which may better suit their environments and ecosystem, allowing wider adoption.

You can download the new image at the [official Fedora IoT page](https://fedoraproject.org/iot/). Also see the [documentation](https://docs.fedoraproject.org/en-US/iot/).


### 389 Directory Server 3.0.0
Fedora 40 provides a new major release of 389 Directory Server, a significant upgrade from version 2.4.4 available in previous releases.

One major change is that, starting with this version, new instances are created using LMDB by default, instead of BerkeleyDB which was the default previously. See [here](https://www.port389.org/docs/389ds/FAQ/Berkeley-DB-deprecation.html) for more information.


### Switch pam_userdb from BerkeleyDB to GDBM
`pam_userdb` was built with support for BerkeleyDB, but this project is no longer maintained as open source, so it has been replaced by GDBM in Fedora 40. See the [Fedora System Administrator's Guide](https://docs.fedoraproject.org/en-US/fedora/latest/system-administrators-guide/pam_userdb/) for information about how to convert.


### Support for the `enumeration` feature has been removed for AD and IPA backends
The `enumeration` feature provides the ability to list all users or groups using
`getent passwd` or `getent group' without arguments. Support for the `enumeration`
feature has been removed for AD and FreeIPA providers.

### `sss_ssh_knownhostsproxy` tool will be replaced in future releases
`sss_ssh_knownhostsproxy` tool has been deprecated and will be replaced by a new, more
efficient tool. See [upstream ticket](https://github.com/SSSD/sssd/issues/5518)
for details.

### Removing SSSD `files provider`
Previously deprecated SSSD "files provider" feature that allows handling of local users has been removed in Fedora 40. This does not affect default configuration where local users are handled by glibc module (`libnss_files.so.2`), which is most cases. In case of specific configuration that requires SSSD to handle local users (smart card authentication or session recording of local users), switch to `proxy provider` instead. If you fall into one of these use cases, see the [upstream documentation](https://sssd.io/docs/files-provider-deprecation.html) for more details.

### Authselect minimal profile replaced by local
The `minimal` profile for Authselect is now replaced by `local`. The new `local` profile is based on `minimal` but gains additional optional features, it is used to serve local users and groups without SSSD. This migration from `minimal` to `local` profile is performed automatically with a new installation or upgrade to Fedora 40 and users are not affected. However, users should adapt their scripts to the new `local` profile since the `minimal` profile is no longer available.


### `bogofilter` to use SQLite

Bogofilter (`bogofilter` package) is a fast anti-spam filtering mechanism that uses Bayesian statistical analysis to classify emails as either spam or non-spam. It uses Berkeley DB (`libdb` package) as its database engine for storing word probabilities and other relevant data used in the filtering process.

With this release, Bogofilter switched its database engine from Berkeley DB to SQLite, because Fedora deprecated the `libdb` package.

Bogofilter supports only one database backend at a time, therefore the updated `bogofilter` package will be unable to process the `libdb` data. As a result, the new package provides a migration script. Alternatively, you can migrate your word lists manually with this command `bogomigrate-berkeley ~/.bogofilter/wordlist.db`.


### Podman 5
The `podman` container engine has been upgraded to version 5, which provides multiple bug fixes and enhancements. Notable changes include:

* Dropped support for `cgroups` version 1 (environments have to switch to `cgroups` version 2)
* Deprecated Container Networking Interface (CNI) plugins (environments have to switch to the `netavark` network stack)
* Deprecated BoltDB
* Set `passt` as the default rootless network service instead of `slirp4netns`
* Improved handling of the `containers.conf` file
* Isolated `podman` bindings to ensure improved usability

For full extent of updates, see the [upstream release notes](https://github.com/containers/podman/blob/main/RELEASE_NOTES.md#500).


### ROCm 6

The ROCm stack for graphics processing unit (GPU) computation has been updated to version 6, which provides multiple bug fixes and enhancements. Notable changes include:

* Improved performance in areas like lower precision math and attention layers
* New hipSPARSELt library to accelerate AI workloads through the AMD sparse matrix core technique
* Latest support for AI frameworks like PyTorch, TensorFlow, and JAX
* New support for libraries such as DeepSpeed, ONNX-RT, and CuPy

For full extent of updates, see the [upstream release notes](https://rocm.docs.amd.com/en/latest/about/CHANGELOG.html#rocm-6-0-0).

### Stratis 3.6
This upgrade includes new releases of stratisd 3.6.7 and stratis-cli 3.6.0.

These releases include a number of improvements, bug fixes, and housekeeping
changes. The following is a brief summary of the changes.

stratisd 3.6.7 includes a fix to a bug introduced in stratisd 3.6.6 which
caused the stratis-min pool start command to fail if the pool was encrypted
and the password to unlock the pool was specified on the command-line. It
also includes a fix to a bug introduced in stratisd 3.6.4 which prevented
automatically unlocking a pool when mounting a filesystem specified in
/etc/fstab.

stratisd 3.6.6 fixes a bug where it would be possible to misreport the
PID of an already running instance of stratisd when attempting to start
another instance. It also includes restrictions on the size of the string
values in the Stratis pool-level metadata.

stratisd 3.6.5 includes a modification to its internal locking mechanism
which allows a lock which does not conflict with a currently held lock to
precede a lock that does. This change relaxes a fairness restriction that
gave precedence to locks based solely on the order in which they had been
placed on a wait queue.

stratisd 3.6.4 includes a fix for stratisd-min handling of the start command
sent by stratis-min to unencrypted pools. It also captures and logs errors
messages emitted by the thin_check or mkfs.xfs executables.

stratisd 3.6.3 explicitly sets the nrext64 option to 0 when invoking
mkfs.xfs. A recent version of XFS changed the default for nrext64 to 1.
Explicitly setting the value to 0 prevents stratisd from creating XFS
filesystems that are unmountable on earlier kernels.

stratisd 3.6.2 includes a fix in the way thin devices are allocated in order
to avoid misalignment of distinct sections of the thin data device. Such
misalignments may result in a performance degradation.

stratisd 3.6.1 includes a fix to correct a problem where stratisd would fail
to unlock a pool if the pool was encrypted using both Clevis and the kernel
keyring methods but the key in the kernel keyring was unavailable.

stratisd 3.6.0 extends its functionality to allow a user to set a limit on
the size of a filesystem and includes a number of additional enhancements.

The stratis-cli 3.6.0 command-line interface has been extended with an
additional option to set the filesystem size limit on creation and two new
filesystem commands, set-size-limit and unset-size-limit, to set or unset the
filesystem size limit after a filesystem has been created.

All releases include sundry internal improvements, conveniences, and minor
bug fixes.

Please see
https://github.com/stratis-storage/stratisd/blob/patch-3.6.0/CHANGES.txt[the stratisd changelog] and
https://github.com/stratis-storage/stratis-cli/blob/master/CHANGES.txt[the stratis-cli changelog] for further details.


### Drop delta RPMs

Delta RPM (DRPM) is a feature, which reduces the time and data required to update packages by downloading only the differences (deltas) between the old and the new version of an RPM package. Based on your current version and the delta, your system then locally re-assembles a complete RPM package with a new version of software.

With this Fedora release, DRPMs will no longer be generated during the compose process. Also, the DRPM support in `dnf` and `dnf5` will be disabled by default. Some of the most notable reasons for this change are as follows:

* It is not possible to produce DRPMs for all packages, because of the way DRPMs are generated during the compose process. As a result, this can lead to upgrades that involve hundreds of packages, but only a small fraction of them (or none at all) have appropriate DRPMs available in the repository.

* The re-construction of a new RPM version can fail. This causes an additional download of the complete RPM for the new version.

* The presence of DRPMs in repositories inflate the size of the repository metadata. That metadata need to be downloaded by all users, whether the actual upgrade involves DRPMs or not.

This change aims to bring the following benefits:

* Simplification of the compose process for "updates" and "updates-testing" repositories, because the generation of DRPMs is skipped.

* Reduction in bandwidth use for repository metadata updates.

* Reduction of storage requirements in Fedora infrastructure and on repository mirrors due to smaller metadata and dropped DRPMs.

* More reliable upgrades for users.


### Stop downloading filelists by default

Filelists are XML files that provide important metadata and information that facilitate RPM package installation, management, and maintenance.

With this Fedora release, the DNF behavior changed in a sense that the filelists will no longer be downloaded by default. The reason is, the metadata that filelists provide are unnecessary in the majority of use cases and they are large in size. This leads to a significant slowdown in the user experience.

This change aims to bring the following notable benefits:

* Significant reduction in processing time and resource usage for RPM package building, installation, testing environment creation, and others

* Decrease in costs of a Fedora mirror server operation

* Reduction in RAM requirements of the DNF process, which addresses existing issues when you run the Fedora system on low-memory machines such as the Raspberry Pi's

Note that you can still use DNF without filelists metadata when querying file provides located in `/usr/bin`, `/usr/sbin` or `/etc` directories.


### wget2 as wget
The `wget` command in Fedora 40 uses Wget2.

GNU Wget2 is the successor to GNU Wget providing a modern implementation of wget backed by a new library: `libwget2`. The intent to switch from wget 1.x to wget2 is to switch to an implementation that is more actively developed and provides a richer interface for leveraging wget's functionality. 


### Enable IPv4 address conflict detection by default in NetworkManager
IPv4 address conflict detection is now enabled by default in NetworkManager. In other words, [RFC 5527](https://www.rfc-editor.org/rfc/rfc5227) is now enabled by default with an interval of 200 ms.


### Assign individual, stable MAC addresses for Wi-Fi connections
Fedora 40 adopts `stable-ssid` as the default mode for assigning individual, stable MAC addresses to Wi-Fi connections in NetworkManager, enhancing user privacy without compromising network stability.

The change adds a new file, `/usr/lib/NetworkManager/conf.d/22-wifi-mac-addr.conf`, which sets `wifi.cloned-mac-address=stable-ssid` as the default mode for MAC address selection in Wi-Fi connections within NetworkManager. The `stable-ssid` mode generates a different MAC address based on each SSID it uses to connect to a network, which is designed to enhance user privacy by making it more difficult for users to be tracked across networks by their hardware MAC address.

This new default value overrides the NetworkManager default of `preserve` and is applied to all existing and new Wi-Fi profiles in Fedora 40 and later that do not override the default, such as by cloning a specific MAC address in the NetworkManager GUI or independently setting `wifi.cloned-mac-address`.

With the adoption of `stable-ssid` as the default in Fedora 40, upgrading to Fedora 40 will apply this new MAC address generation by default, including on existing Wi-Fi profiles. This can result in potentially breaking changes to Wi-Fi connection behavior, particularly for users of networks with features or restrictions that rely on the device's prior default MAC address.

Users who must maintain consistent MAC addresses for specific networks can address this by manually setting `wifi.cloned-mac-address` to `permanent` for specific profiles:

----
nmcli connection modify [$PROFILE] wifi.cloned-mac-address permanent
----

Replace `[$PROFILE]` with the NetworkManager profile name, which is typically the SSID. To list profiles by name, run `nmcli connection`.

To revert to previous behavior, override the new default by following one of these steps:

* Create a custom configuration file in `/etc/NetworkManager/conf.d/22-wifi-mac-addr.conf`, which can be empty or contain specific configurations. This prevents Fedora from loading its default file in `/usr/lib`.
* Create a higher priority .conf file, such as `/etc/NetworkManager/conf.d/90-wifi-mac-addr.conf`, which sets `wifi.cloned-mac-address`:
+
----
[connection-90-wifi-mac-addr-conf]
wifi.cloned-mac-address=permanent
----

For details on the order in which configuration files are loaded and their priority, refer to `man NetworkManager.conf`. For other available `wifi.cloned-mac-address` options, see the [NetworkManager documentation](https://networkmanager.dev/docs/api/1.46/settings-802-11-wireless.html).


### PostgreSQL 16
Fedora 40 provides version 16 of PostgreSQL. For more information, see the [upstream release notes](https://www.postgresql.org/docs/16/release-16.html).


### SPDX Migration

RPM packages use SPDX identifiers for licenses as a standard. 63 % of the packages and almost all packeges from ELN set have been migrated to [SPDX identifiers](https://spdx.org/licenses/). The remaining packages are estimated to be migrated to SPDX in Fedora 41.

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
