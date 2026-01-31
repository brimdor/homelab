# Fedora f43 Release Notes
*Auto-generated from upstream release notes*


---
## File: desktop.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For Desktop Users


### GNOME now uses Wayland only
The GNOME X11 session has been removed from Fedora Linux. Users previously using GNOME on X11 will be transparently upgraded to the GNOME Wayland session. X11 applications are still supported on GNOME. 


### Set default fallback monospace font
In previous Fedora releases, monospace fonts were implicitly substituted with sans-serif fonts by default configuration file in fontconfig if missing, which was the case for some languages.
This could result in unpredictable behavior once additional font packages were installed.
Fedora 43 fixes this by assigning a tentative default monospace font for languages that were previously missing it.

If you were relying on old behavior, you can use `fonts-tweak-tool` to specify the default monospace font for a certain language.


### gdk-pixbuf2 now uses Glycin sandboxed image loading
`gdk-pixbuf2` now depends on Glycin, the sandboxed image loading framework, which greatly improves security. 
The intent is to provide the same user experience as before, but much has changed behind the scenes. 
All built-in pixbuf loaders have been removed in favor of the Glycin pixbuf loader. 
Most external pixbuf loaders are now obsolete, as Glycin supports the same image formats. 

Accordingly, `avif-pixbuf-loader` from `libavif`, `heif-pixbuf-loader` from `libheif`, `jxl-pixbuf-loader` from `libjxl`,
`rsvg-pixbuf-loader` from `librsvg`, and the standalone package `webp-pixbuf-loader` have all been removed from the distribution. 
Additionally, `gdk-pixbuf-thumbnailer` has been removed in favor of `glycin-thumbnailer`. `libvaif`, `libjxl`, and `librsvg` no longer provide thumbnailers, since they depend on `gdk-pixbuf-thumbnailer`. 
`libheif` still provides its own standalone thumbnailer, although it is redundant with the Glycin thumbnailer.


### Noto color emoji now use COLR
Noto Color Emoji fonts in Fedora now use the [COLRv1](https://learn.microsoft.com/en-us/typography/opentype/spec/colr) format. The COLRv1 format is a color scalable font compared with the previous color bitmap fonts. 

Users should not notice any changes except for a smaller file size.

---
## File: developers.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For Developers


### Python 3.14
The Python stack in Fedora has been updated from version 3.13 to version 3.14, the latest major release of the Python programming language.

For more information, see the [upstream "What's new" document](https://docs.python.org/dev/whatsnew/3.14.html#what-s-new-in-python-3-14), and especially the [Porting to Python 3.14](https://docs.python.org/dev/whatsnew/3.14.html#porting-to-python-3-14) section.


#### python-async-timeout is now deprecated
The `python-async-timeout` package has been deprecated in Fedora. Developers are encouraged to migrate to asyncio.Timeout in Python 3.11+ for improved compatibility with the standard library. 


#### python-nose retired
The `python3-nose` package has been retired due to long-term lack of upstream development.


### GNU toolchain update
The GNU toolchain in Fedora 43 has been updated to:

* GNU C Compiler (`gcc`) 15.2
* GNU Binary Utilities (`binutils`) 2.45
* GNU C Library (`glibc`) 2.42
* GNU Debugger (`gdb`) 16.3

Also see the upstream release notes for [GCC](https://gcc.gnu.org/gcc-15/changes.html), [Binutils](https://lists.gnu.org/archive/html/info-gnu/2025-07/msg00009.html), [GLibC NEWS](https://sourceware.org/git/?p=glibc.git;a=blob;f=NEWS;hb=HEAD), and [GDB NEWS](https://www.sourceware.org/gdb/news/).


#### Gold linker deprecated
The Gold linker has been deprecated and will eventually be removed from Fedora entirely due to upstream development having stopped.
Three other linkers are still available to developers (`ld.bfd`, `lld` and `mold`), so there is still plenty of choice. 


### Golang 1.25
The latest stable release of the Go programming language is now available in Fedora 43.

For more information, see the [upstream release notes](https://tip.golang.org/doc/go1.25).

#### Golang packages are now vendored by default
Fedora now uses vendored dependencies as the default and preferred option when building Golang applications, instead of relying on pre-packaged dependencies.
This includes adopting [Go Vendor Tools](https://fedora.gitlab.io/sigs/go/go-vendor-tools/), a new set of tooling to handle license scanning, generating a cumulative SPDX expression for all dependencies, and creating reproducible vendor archives.
This change aims to simplify packaging Golang applications in Fedora. Users should not see any change in behavior.


### LLVM 21
LLVM sub-projects in Fedora have been updated to version 21.
There has been a soname version change for the llvm libraries, and an llvm20 compat package has been added to ensure that packages that currently depend on `clang` and `llvm` version 20 libraries will continue to work.

Other notable changes include:

* Built with PGO: The `llvm` package is now built with PGO optimization, so users of its libraries and binaries should see some performance improvements. For example, `clang` should be noticeably faster compiling C and C++ files.
* Undoing the prefix changes from LLVM 20: This change was made in rawhide and f42 after the f42 release, so it is already done. See https://pagure.io/fesco/issue/3414.

More information is available in the [upstream release notes](https://releases.llvm.org/21.1.0/docs/ReleaseNotes.html).



### Ruby on Rails 8.0
The Ruby on Rails stack has been upgraded from version 7.0 in Fedora 42 to version 8.0 in Fedora 43.
Notable changes include:

* Trifecta of new database-backed adapters named Solid Cable, Solid Cache, and Solid Queue (not part of Fedora at the moment).
* SQLite ready for production.
* Sprockets replaced with Propshaft.
* Generating the authentication basics.

See the [upstream release notes](https://guides.rubyonrails.org/8_0_release_notes.html) for more information.


### Tomcat 10.1
The Tomcat application server has been upgraded to version 10.1 in Fedora 43.

Changes in this version include:

* Apache Tomcat 10.1.x requires Java 11 or later.
* Specification API Breaking Changes: There is a significant breaking change between Tomcat 9.0.x and Tomcat 10.1.x. 
The Java package used by the specification APIs has changed from `++javax.*++` to `++jakarta.*++`. 
It will be necessary to recompile web applications against the new APIs. 
See the [Change page on the Fedora Wiki](https://fedoraproject.org/wiki/Changes/Tomcat10ChangeProposal#Upgrade/compatibility_impact) for details.
* Other Specification API changes: 
** Jakarta Servlet 6.0 API: The Java package has changed from `javax.servlet` to `jakarta.servlet`. A new method, `Cookie.setAttribute(String name, String value)` has been added. The process for decoding and normalizing URIs has been clarified. New methods and classes have been added to provide access to unique identifiers for the current request and/or associated connection.
** Jakarta Server Pages 3.1 API: The Java package has changed from `javax.servlet.jsp` to `jakarta.servlet.jsp`. Added an option to raise a `PropertyNotFoundException` when an EL expression contains an unknown identifier.
** Jakarta Expression Language 5.0: The Java package has changed from `javax.el` to `jakarta.el`. The EL API now uses generics where appropriate. The deprecated `MethodExpression.isParmetersProvided()` method has been removed from the API.
** Jakarta WebSocket 2.1: The Java package has changed from `javax.websocket` to `jakarta.websocket`. The packaging of the API JARs has changed to remove duplicate classes. The server API now has a dependency on the client API JAR.
** Jakarta Authentication 3.0: The Java package has changed from `javax.security.auth.message` to `jakarta.security.auth.message`.
* Internal Tomcat APIs: Whilst the Tomcat 10 internal API is broadly compatible with Tomcat 9, there have been many changes at the detail level and they are not binary compatible. Developers of custom components that interact with Tomcat's internals should review the JavaDoc for the relevant API.
* `web.xml` defaults: `conf/web.xml` sets the default request and response character encoding to UTF-8.
* Session management: Session persistence on restart has been disabled by default. It may be re-enabled globally in `conf/context.xml` or per web application.
* HTTP/2: The configuration settings that were duplicated between the HTTP/1.1 and HTTP/2 connectors have been removed from the HTTP/2 connector which will now inherit them from the associated HTTP/1.1 connector.
* Logging: The logging implementation now only creates log files once there is something to write to the log files.
* Access Log Patterns: To align with httpd, the `%D` pattern now logs request time in microseconds rather than milliseconds. To log request time in milliseconds, use `++%{ms}T++`.

See the [upstream changelog](https://tomcat.apache.org/tomcat-10.1-doc/changelog.html) for additional information.


### Haskell GHC 9.8 and Stackage LTS 23

For Fedora 42, the main GHC Haskell compiler package have been from version [9.6.6](https://www.haskell.org/ghc/download_ghc_9_6_6.html) to the latest stable [9.8.4](https://www.haskell.org/ghc/download_ghc_9_8_4.html) release (rebasing the ghc package from the [ghc9.8](https://src.fedoraproject.org/rpms/ghc9.8/) package). Along with this, Haskell packages in [Stackage](https://www.stackage.org/) (the stable Haskell source package distribution) have been updated from the versions in [LTS 22](https://www.stackage.org/lts-22) to latest [LTS 23](https://www.stackage.org/lts-23) release. Haskell packages not in Stackage have been updated to the latest appropriate version in the upstream [Hackage](https://hackage.haskell.org/) package repository.

For full information about this release, see the [upstream release notes](https://downloads.haskell.org/~ghc/9.8.4/docs/users_guide/9.8.4-notes.html) and [migration guide](https://gitlab.haskell.org/ghc/ghc/-/wikis/migration/9.8).


### The Hare programming language

Fedora 43 introduces packages for Hare, a systems programming language designed to be simple, stable, and robust.
Hare uses a static type system, manual memory management, and a minimal runtime. It is well-suited to writing operating systems, system tools, compilers, networking software, and other low-level, high performance tasks. 

The Hare toolchain on Fedora includes:

* `hare` (build driver)
* `harec` (compiler front-end, already available in Fedora)
* `qbe` (compiler back-end, already available in Fedora)
* `binutils` (for assembly and static linking)
* `gcc` (for dynamic linking, it also works with other C compilers)

The Hare tool chain can target the `x86_64`, `aarch64`, and `riscv64` architectures, and is configured to rely by default on `gcc-<arch>-linux-gnu` and `binutils-<arch>-linux-gnu` for cross compilation.

The `hare` source package includes the following:

* `hare` (build driver, `haredoc` utility, and manuals)
* `hare-stdlib` (standard library)
* `hare-rpm-macros` (packaging utilities)

In addition, a `hare-update` package is provided to assist Hare developers dealing with breaking changes when a new Hare release is available, until the language and its standard library become stable. 

For more information about Hare, see the [upstream documentation](https://harelang.org/documentation/) and [specification](https://harelang.org/specification). A [tutorial](https://harelang.org/tutorial) is also available on the official website.


### Java
Release 43 makes `java-25-openjdk` available in Fedora, the latest LTS version released Sept. 2025.

The `java-21-openjdk` is still available in F43 and will continue to be in F44. It will be removed in F45.

In Fedora 43 both openjdk versions provide "java" equally. There is no "system" or "default" JDK anymore. Users can (and should) choose which version to use, and can mix and match Java versions for development and runtime. Several instances of a software, e.g. Tomcat, can execute with different Java versions. Conventionally, the most recent version will likely become the systemwide used default one, but there is no guarantee. Use `alternatives --config java` to select the version to be used systemwide by default.

Upgrading from release 42 with installed java-21-openjdk, just updates Java 21 to release 43. The upgrade does not automatically update to Java 25. The administrator must install these separately.

For more information about Java 25, see the [JDK 25 Features and Release notes](https://jdk.java.net/25/).

For technical details of this change, see the [Change page](https://fedoraproject.org/wiki/Changes/Java25AndNoMoreSystemJdk).


### TBB2022.2.0

The `tbb` package contains Intel's oneAPI Threading Building Blocks, a library for breaking computations into parralel tasks. In Fedora 43, this package has been upgraded from version 2022.0.0 to version 2022.2.0.

Due to an ABI change, non-Fedora packages that use `tbb` will likely need to be rebuilt. Version 2022.2.0 is API-compatible with version 2022.0.0, so a simple rebuild should suffice.

For detailed information, see the [upstream release notes for TBB 2022.1.0 and TBB 2022.2.0](https://github.com/uxlfoundation/oneTBB/blob/master/RELEASE_NOTES.md).


### Perl 5.42
Fedora 43 provides Perl 5.42.0, a new stable release that focuses on improving performance, refining existing features, and adding new experimental capabilities. 

**Core enhancements**

* New `any` and `all` Operators: Two new experimental keywords, `any` and `all`, are introduced for more efficient list processing. They're designed to short-circuit, so they stop processing the list as soon as the result is known. They're compiled directly into the core, making them faster than their counterparts from the `List::Util` module.
* Lexical Methods: You can now declare private, lexical methods using the `my method` syntax. The new -`++>&++` operator allows you to call these methods, ensuring they're only visible within their defined scope.
* `source::encoding` Pragma: A new pragma is available to explicitly declare whether a source file is encoded in ASCII or UTF-8. This helps to catch encoding-related errors early during development.
* Expanded `CORE::` Namespace: Built-in functions like `chdir` and `rand` can now be safely used as first-class subroutine references. This gives you more flexibility when passing core functions as arguments.
* `:writer` Field Attribute: When defining classes with `use feature 'class'`, you can now use the `:writer` attribute on scalar fields to automatically generate setter accessors.

**Reconsidered features**

* `smartmatch` and `switch` Reinstated: The `switch` and `smartmatch (~~)` features, which were previously scheduled for removal, have been granted an indefinite reprieve. They are now available, but you must enable them with a specific feature flag.
* Apostrophe as Package Separator: The legacy use of a single apostrophe (`) as a package separator has been reinstated by default after community feedback. You can still control this behavior with a feature flag.

** Other updates**

* This release also includes performance improvements to the `tr///` operator, updates to Unicode 16.0 support, and various bug fixes related to locale handling, `goto`, and `eval`.

For more detailed information, refer to the official [perldelta for 5.42.0](For more detailed information, refer to the official perldelta for 5.42.0 documentation. ) documentation. 


### Maven 4
Maven 4 is a new major version of Maven after 15 years of Maven 3. It brings many improvements, but also breaking changes. Fedora 43 provides Maven 4 as the `maven4` package, making it installable in parallel to Maven 3.

See the [What's new in Maven 4?](https://maven.apache.org/whatsnewinmaven4.html) post and the [upstream docs](https://maven.apache.org/ref/4.0.0-rc-4/) for more details.


### Idris 2
Idris 2 is a dependently typed practical functional programming language, now available in Fedora 43.
It is a complete rewrite of Idris 1 (which was written in Haskell and is now deprecated) on top of a Scheme compiler.

For details, see the [upstream documentation](https://idris2.readthedocs.io/en/latest/), including a list of changes compared to Idris 1 and an Idris 2 tutorial.


### Rust

#### async-std is now deprecated
The `async-std` Rust crate is no longer maintained and is now considered deprecated in favor of the `smol` crate.

#### gtk3-rs, gtk-rs-core v0.18, and gtk4-rs v0.7 are now removed
The Rust bindings for GTK3 (and related libraries) were marked as deprecated in Fedora 43 due to lack of upstream maintenance.
In Fedora 43, they are completely removed.


### Debuginfod IMA verification
The `debuginfod` client tools used to auto-download debuginfo & source code into tools like `gdb` now cryptographically verify the integrity of the downloaded files from the Fedora debuginfod server. 
This setting is appropriate for normal Fedora koji-signed release/update RPMs. 
However if your workflow also involves unsigned flatpak RPMs (`++%dist ".fc#app#"++`), then you may need to manually remove `ima:enforcing` from your `$DEBUGINFOD_URLS`.


### Free Pascal cross-compilers
Fedora Linux 43 ships with cross-compilation support for the Free Pascal Compiler, through several new packages. 
Users interested in cross-compiling for MS Windows should install the `fpc-units-x86_64-win64` or `fpc-units-i386-win32 packages`. 
For cross-compiling for Linux to other architectures, install the appropraite `fpc-units-$ARCH-linux` package. 
Note that you may need to perform some extra steps if you want your cross-compiled Pascal programs to link against external libraries. 

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

Graphical installation of Fedora requires a minimum screen resolution of **1024x768**. Owners of devices with lower resolution, such as some netbooks, should use text or VNC installation.

Once installed, Fedora will support these lower resolution devices. The minimum resolution requirement applies only to graphical installation.


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


### Changes in the Anaconda installer

#### Fedora spins now use the new WebUI installer

Fedora 42 has introduced a new, redesigned graphical installer interface using a new, browser-based WebUI, which was available on Fedora Workstation.
In Fedora 43, the same installer is now also used on Fedora KDE Edition, as well as some of the Spins.

#### No more support for installs on MBR-partitioned disks in UEFI mode on x86

Starting with Fedora 43, the installer no longer supports installing Fedora on disks using a Master Boot Record (MBR) while in UEFI boot mode on 32-bit x86 systems.
Instead, the installer will enforce the use of a GUID Partition Table (GPT), which is a significantly more modern standard, and was already the default previously on some hardware configurations.
Existing 32-bit UEFI systems with MBR-partitioned disks can be upgraded like normal, only new installations are affected.

#### Anaconda now uses DNF5

Fedora as a whole has switched to DNF5 in the 41 release for general package management and image building. 
Starting with Fedora 43, Anaconda is now also using DNF5 on the backend. The change should not be visible to most users.

#### Modularity support removal

Since the Fedora Modularity project has been deprecated, supports for package modularity has now also been removed from Anaconda.
This change is related to the switch to DNF5, as DNF5 no longer supports modularity either, so this allows Anaconda to be upgraded to DNF5.

#### Default /boot partition is now 2G

Fedora Linux 43 has raised the size of the default `/boot` partition to 2 GiB. 
This is to accommodate increases in boot data over the past several releases and to maintain a usable experience. 
Users of older releases may be advised to consider reinstalling instead of upgrading to increase the `/boot` partition size. 

### Automatic updates by default on Fedora Kinoite

Updates to both the system and all Flatpaks on Fedora Kinoite are now downloaded automatically and applied on the next reboot.
The change applies to all systems, whether newly installed or updated to Fedora 43, unless the autoupdate setting has been changed before.

You can change the frequency of automatic updates (or disable them completely, though this is not recommended) in system settings, under the **Software Updates** tab.


### Stratis 3.8.5: stratisd 3.8.5 and stratis-cli 3.8.2

Stratis 3.8.5, which consists of `stratisd 3.8.5` and `stratis-cli 3.8.2` includes
a number of significant enhancements and modifications.

#### stratisd

For `stratisd`, the release makes improvements to the Stratis support for mounting
filesystems at boot. It introduces a new systemd unit file, 
`stratis-fstab-setup-with-network@.service`, which should be used when a filesystem's pool
requires unlocking with the network present, as is the case when a pool is encrypted using
NBDE (network-bound disk encryption). The fstab entry for the filesystem must include the
`_netdev` option if this systemd unit file is used.

If the `stratis-fstab-setup-with-network@service` unit is used and the `_netdev` option is
omitted in the same fstab entry, systemd will calculate a cyclic dependency,
and the boot process will fail.

An example fstab entry for a filesystem on a pool that is encrypted using NBDE should look
something like this:

[,console]
----
/dev/stratis/<POOL_NAME>/<FILESYSTEM_NAME> <MOUNTPOINT> xfs defaults,_netdev,x-systemd.requires=stratis-fstab-setup-with-network@<POOL_UUID>.service 0 2
----

If a filesystem's pool does not require that the network is up to be unlocked then the fstab
entry may use the existing `stratis-fstab-setup@.service` unit instead.

Additionally `stratisd` takes responsibility for maintaining the key used to encrypt a Stratis
pool, so that it is guaranteed to be present in the kernel keyring if an automatic pool maintenance
action needs to be performed on an encrypted pool. `stratisd` updates the new `VolumeKeyLoaded`
D-Bus property on the affected pool with an error message if the key is not loaded.

`stratisd` also exposes additional information about stopped pools in the StoppedPools property.

#### stratis-cli

For `stratis-cli`, the release fixes a bug where a user would be unable to start an
encrypted pool previously created with any Stratis release less than 3.8.0.

`stratis-cli` also exposes more information about a stopped pool in its detail view. 


### Confidential Virtualization Host for Intel TDX
Fedora virtualization hosts running on suitably configured Intel Xeon hardware now have the ability to launch confidential virtual machines using the Intel TDX feature. 

Fedora has provided support for launching confidential virtual machines using KVM on x86_64 hosts for several years, using the SEV and SEV-ES technologies available from AMD CPUs, and since Fedora 41, using the SEV-SNP technology. In the Fedora 42 release, support for the Intel SGX platform was introduced, and this change builds on that work to allow creation of Intel TDX guests on Fedora hosts. Intel TDX provides confidential virtualization functionality that is on a par with the recent AMD SEV-SNP support. 


### PostgreSQL 18
PostgreSQL in Fedora 43 (the `postgresql` and `libpq` components) has been upgraded to major version 18. This continues the versioned packaging structure introduced in Fedora 40. 

See the [upstream release notes](https://www.postgresql.org/docs/18/release-18.html) for more information and notes on migration.

[CAUTION]
The update will break Postgresql runtime and requires extra effort! Follow the advice at https://docs.fedoraproject.org/en-US/fedora-server/#_updating_to_fedora_43[Fedora Server Docs] or https://bugzilla.redhat.com/show_bug.cgi?id=2411778#c1[Bugzilla Bug #2411778].


### Read-only BDB support in 389 Directory Server
Starting from 389-ds-base version 3.1.3, the 389 Directory Server no longer supports the deprecated BerkeleyDB, so the LDMB database must be used. Users still using BerkeleyDB will have to migrate their data. In Fedora this change is available starting from Fedora 43 (Version 3.2.0 that was also originally planned for Fedora 43 is delayed.)

Directory server instances created since Fedora 40 and using the default LMDB database are not impacted (that is typically the case for FreeIPA users).
However, users still using BerkeleyDB (either because they have not yet migrated or because they explicitly choose to use BerkeleyDB) are required to migrate to LMDB.

If this step is not done, the instance will not be able to start after the upgrade, and the following error message is displayed in the dirsrv error log and in the system journal: 

[,console]
----
bdb implementation is no longer supported. Directory server cannot be started without migrating to lmdb first. To migrate, please run: dsctl instanceName dblib bdb2mdb
----

Users then need to migrate the data either using the `dsctl` command, or manually by following the steps in the [upstream FAQ](https://www.port389.org/docs/389ds/FAQ/Berkeley-DB-deprecation.html#manual-method---export-to-ldif).


### Dovecot 2.4
The Dovecot e-mails server has been updated to version 2.4 in Fedora 43. This is the latest major update, released after 7 years of development.

Note that Dovecot 2.4 configuration is not totally compatible with the previous version (2.3). See the [Upgrading Dovecot CE from 2.3 to 2.4](https://doc.dovecot.org/2.4.1/installation/upgrade/2.3-to-2.4.html) document upstream.

For more information about this release, see the [upstream release notes](https://github.com/dovecot/core/releases/tag/2.4.0). 


### MySQL 8.4 as default
MySQL 8.4 is now the default version of MySQL in Fedora.

Those who wish to continue using the previous default version, MySQL 8.0, can use the `mysql-8.0-server` package.

For information about the latest releases, see the following links:

* [8.1 release notes](https://dev.mysql.com/doc/relnotes/mysql/8.1/en/)
* [8.2 release notes](https://dev.mysql.com/doc/relnotes/mysql/8.2/en/)
* [8.3 release notes](https://dev.mysql.com/doc/relnotes/mysql/8.3/en/)
* [8.4 release notes](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/)


### RPM 6.0
Fedora 43 updates the RPM packaging system to version 6.0. This release provides several security improvements, such as:

* OpenPGP keys are referred to by their fingerprint or full key id where fingerprint not available (compared to the short keyid in previous versions).
* OpenPGP keys can be updated with `rpmkeys --import <key>` and corresponding API(s).
* Support for multiple signatures per package.
* Support for automatic signing on package build (mainly for local use).
* Support for OpenPGP v6 keys and signatures (including PQC).
* Support for signing with Sequoia-sq as an alternative to GnuPG.

For full information about this release, see the [upstream release notes](https://rpm.org/wiki/Releases/6.0.0). The [Road to RPM 6.0](https://github.com/rpm-software-management/rpm/discussions/3602) post also provides details in a more easily digestible format.
Slightly smaller (in the range of a few megabytes) initrd sizes and faster boots. See https://github.com/coreos/fedora-coreos-tracker/issues/1247#issuecomment-1179490347 for some measurements. We did the change in Fedora CoreOS to reduce the size of the initrd to save disk space in the /boot partition. 


### initrd is now compressed by zstd by default
The compression algorithm used by `dracut` when generating an initrd has been changed from `xz` to `zstd`, and Dracut now depends on `zstd` to ensure it is available. This should result in slightly smaller initrd sizes and slightly faster boot times.


### YASM is deprecated and has been replaced with NASM
The YASM assembler has been deprecated and no new packages should depend on it. Packages that require it to build are now built using NASM where possible. 


### Modular packaging for GnuPG2
The previously monolithic GnuPG package (`gnupg2`) has been modularized, with several tools and non-essential utilities having been split into separate subpackages. The non-essential utilities (in `gnupg2-utils`) and some services that are unused on most systems are no longer installed by default. 


### SSSD Identity Provider (IdP) support
SSSD in Fedora 43 provides a new generic identity and authentication provider for Identity Providers (IdPs). Initial support includes Keycloak and Entra ID. You can now configure SSSD to read users and groups directly from these IdPs and enable user authentication using the OAUTH 2.0 Device Authorization Grant (RFC 8628). See the sssd-idp(5) man page for more information and configuration examples.

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
