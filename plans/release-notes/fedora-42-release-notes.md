# Fedora f42 Release Notes
*Auto-generated from upstream release notes*


---
## File: desktop.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For Desktop Users


### Fedora COSMIC Spin

This release introduces the Fedora COSMIC Spin, which offers many unique features, for example:

* Hybrid per-workspace tiling management.
* Window stacks with tabs to switch between windows.
* Customization features that integrate with the GTK toolkit.


### XFCE 4.20
Fedora 42 ships with version 4.20 of the XFCE desktop environment. A notable change is experimental Wayland support.

For more information about this release, see the [upstream changelog](https://www.xfce.org/download/changelogs/4.20).


### LXQt 2.1
The LXQt desktop environment has been updated to version 2.1 in Fedora 42, and now uses Wayland by default through `miriway`.

See the [upstream release announcement](https://lxqt-project.org/release/2024/11/05/release-lxqt-2-1-0/) for more details about this release.


### KDE Plasma is now a full Edition
Fedora Linux 42 promotes the Fedora KDE Plasma Desktop variant to full Edition status. 


### FEX emulator on Fedora
Fedora now provides FEX, a fast emulator that allows one to run x86 and x86-64 binaries on an AArch64 Linux host. FEX requires a number of supporting components, including a RootFS image, and integration with muvm to support 16k page-size hosts. The purpose of this Change is to integrate FEX itself and its supporting components into Fedora Linux, to provide a delightful out-of-box experience for users that want to run x86 and x86-64 binaries on their aarch64 systems. This also includes integration into the AArch64 Fedora KDE spin as a non-blocking component of the spin.

To start using FEX, run `dnf install @fex-x86-emulation`.

There is a detailed Q&A section on the [Change page](https://fedoraproject.org/wiki/Changes/FEX#Feedback) which provides additional information about FEX.


### Replace SDL 2 with sdl2-compat using SDL 3
Applications that use SDL 2 (typically games) will now transparently use SDL 3 through the `sdl2-compat` package. This makes it so applications that historically used SDL 2 now use SDL 3. The change is completely automatic and users should not notice any difference other than potentially slightly smoother performance.


### IBus 1.5.32

Fedora 42 provides version 1.5.32 of the IBus internationalization library. Notable improvements include:

* Support for the Wayland input-method protocol version 2 which is allowed by some Wayland desktop sessions likes Sway, Hyprland, COSMIC desktop sessions
* IBus now can show candidate popups for non-Wayland applications of XIM and GTK2 in Wayland desktop sessions
* The `ibus start` command is now enhanced to work for the Wayland input-method protocol version 2

See [here](https://desktopi18n.wordpress.com/2025/01/13/ibus-1-5-32-plan/) for information on IBus configuration in various desktop environments.


### ibus-speech-to-text feature
The new `ibus-speech-to-text` package introduces voice dictation capabilities for any application that supports IBus input methods. The feature uses the VOSK speech recognition toolkit that does not require Internet connectivity.

Benefits to users:

* Accessibility and user productivity improvements through voice input
* Offline voice recognition to preserve user privacy
* Seamless integration with existing IBus infrastructure
* Support for multiple languages through downloadable models


### ibus-libpinyin 1.16
The ibus-libpinyin 1.16 library has been updated to version 1.16 in Fedora 42. Notable new features include:

* Support for punctuation candidates
* Support for custom keyboard layouts
* The kbd: keys now scroll the candidate page up/down
* Displaying Lua converters in the input method menu
* Notifying the user when import of a pinyin or table file is finished


### X86 MIPI camera hardware enablement

Ferdora 42 expands out of the box support for additional integrated cameras found on x86 laptops and tablets. 
This change is part of an ongoing effort in camera enablement on Fedora, and follows a similar change in 
[Fedora 41](https://docs.fedoraproject.org/en-US/fedora/f41/release-notes/desktop/#ipu6-cameras).

---
## File: developers.adoc

:experimental:
include::partial$entities.adoc[]

## Changes in Fedora {PRODVER} For Developers


### The Copilot Runtime Verification Framework
Fedora 42 provides the [Copilot Language and Runtime Verification System](https://copilot-language.github.io/) is a stream-based runtime-verification framework for generating hard real-time C code, , developed for NASA. It allows users to write concise programs in a simple but powerful way using a stream-based approach.

Programs can be interpreted for testing, or translated C99 code to be incorporated in a project, or as a standalone application. The C99 backend ensures us that the output is constant in memory and time, making it suitable for systems with hard realtime requirements.

You can get started by installing the `ghc-copilot` package. For more information, see the following upstream documentation:

* https://copilot-language.github.io/documentation.html
* https://github.com/Copilot-Language/copilot
* https://ntrs.nasa.gov/citations/20240010993


### Ruby 3.4

The latest stable release of this programming language is now available in Fedora 42. Some notable changes include:

* The default parser changed from _parse.y_ to _Prism_ to improve maintainability, error tolerance, portability, and performance.

* YJIT compiler now offers better performance across most benchmarks on both x86-64 and arm64 CPU architectures.

* The socket library features Happy Eyeballs Version 2 to provide efficient and reliable network connections adapted for modern Internet environments.

* Block passing is no longer allowed in index.

* The toplevel name `::Ruby` is now reserved.

* `rb_newobj` and `rb_newobj_of` (and corresponding macros `RB_NEWOBJ`, `RB_NEWOBJ_OF`, `NEWOBJ`, `NEWOBJ_OF`) were removed.

* Removed the deprecated function `rb_gc_force_recycle`.

For more details, see the [upstream release notes](https://www.ruby-lang.org/en/news/2024/12/25/ruby-3-4-0-released/).



### PHP 8.4

The latest stable release of this programming language is now available in Fedora 42. Notable changes include:

* Property hooks to support computed properties that can be natively understood by IDEs and static utilities without the need for docblock comments.

* The scope to write to a property can now be controlled independently from the scope to read the property.

* The new `#[\Deprecated]` attribute.

* New functions `array_find()`, `array_find_key()`, `array_any()`, and `array_all()`

* New subclasses `Pdo\Dblib`, `Pdo\Firebird`, `Pdo\MySql`, `Pdo\Odbc`, `Pdo\Pgsql`, and `Pdo\Sqlite`

For more details, see the [upstream release notes](https://www.php.net/releases/8.4/en.php).


### GNU Toolchain update

The GNU toolchain in Fedora 41 has been updated to:

* GNU C Compiler (gcc) 15
* GNU Binary Utilities (binutils) 2.44
* GNU C Library (glibc) 2.41
* GNU Debugger (gdb) 15+

Also see the upstream release notes for [GCC](https://gcc.gnu.org/gcc-15/changes.html), [Binutils](https://lists.gnu.org/archive/html/info-gnu/2025-02/msg00001.html), [GLibC NEWS](https://sourceware.org/git?p=glibc.git;a=blob;f=NEWS;hb=HEAD#l47), and [GDB NEWS](https://www.sourceware.org/gdb/news/).


### LLVM 20
LLVM sub-projects in Fedora have been updated to version 20.

There is a soname version change for the llvm libraries, and an `llvm19` compat package added to ensure that packages that currently depend on clang and llvm version 19 libraries will continue to work.

Other notable changes:

* Install Prefix Changes: The install prefix for all new llvm packages will be `/usr/lib64/llvm$VERSION/` instead of `/usr/`. There will be symlinks for each binary and library added to `/usr/` which point to the corresponding binary in `/usr/lib64/llvm$VERSION/` The goal of this change is to reduce the differences between the compat and non-compat versions so that it it easier for packages that depend on llvm to switch between the two.

* Merging more packages into `llvm`: In Fedora 41, we merged the `clang`, `libomp`, `compiler-rt`, `lld`, `python-lit`, and `lldb` packages into the `llvm` SRPM. For Fedora 42, we will also be merging `llvm-bolt`, `polly`, `libcxx`, and `mlir` into the `llvm` SRPM.


### Golang 1.24

The latest stable release of the Go programming language is now available in Fedora 42. Notable changes include:

* Go modules can now track executable dependencies using `tool` directives in `go.mod`.
* The new `-tool` flag for go get causes a tool directive to be added to the current module for named packages in addition to adding require directives.
* The new `tool` meta-pattern refers to all tools in the current module. This can be used to upgrade them all with `go get tool` or to install them into your GOBIN directory with `go install tool`.
* Executables created by `go run` and the new behavior of `go tool` are now cached in the Go build cache. This makes repeated executions faster at the expense of making the cache larger.
* The `go build` and `go install` commands now accept a `-json` flag that reports build output and failures as structured JSON output on standard output. For details of the reporting format, see `go help buildjson`.
* Furthermore, `go test -json` now reports build output and failures in JSON, interleaved with test result JSON. These are distinguished by new `Action` types, but if they cause problems in a test integration system, you can revert to the text build output with GODEBUG setting `gotestjsonbuildtext=1`.
* The new `GOAUTH` environment variable provides a flexible way to authenticate private module fetches. See `go help goauth` for more information.
* The `go build` command now sets the main module's version in the compiled binary based on the version control system tag and/or commit. A `+dirty` suffix will be appended if there are uncommitted changes. Use the `-buildvcs=false` flag to omit version control information from the binary.
* The new GODEBUG setting `toolchaintrace=1` can be used to trace the go command's toolchain selection process.

For more iformation, see the [upstream release notes](https://tip.golang.org/doc/go1.24).


### Tcl/Tk 9
Tcl (Tool Command Language) and Tk (TCL graphical toolkit) have been rebased to version 9 in Fedora 42. There are some major incompatibilities and it's unrealistic to port all depending packages, so compat Tcl/Tk 8 packages (`tcl8` and `tk8`) have been provided. 

New features include:

* 64-bit Capacity: Data values larger than 2Gb.
* Unicode and Encodings: full codepoint range, added encodings, encoding profiles to govern I/O, and more.
* Access to OS facilities: notifications, print, and tray systems.
* Scalable Vector Graphics: partial support in images, extensive use to enable scalable widget and theme appearances.
* Platform Features and Conventions: many improvements, including two-finger gesture support where available.

For more information about this release, see the [upstream release notes](https://www.tcl-lang.org/software/tcltk/9.0.html).


### GNOME Shell extension Dependency Generator
Fedora 42 provides a new GNOME Shell extension dependency generator, packaged as `gnome-shell-extension-rpm-macros`.

GNOME Shell extensions ship with a `metadata.json` that lists the supported versions of GNOME Shell. This data was previously unused in Fedora when packaging an extension, unless the package maintainer explicitly transfered this information to the spec -- and then kept it up to date. 

Starting with Fedora 42, the binary RPM automatically declares its dependency on the correct versions of GNOME Shell, ensuring that we will discover after mass rebuild if some extensions need to be updated because they will FTI. This results in an improved user experience for Fedora users, because extensions that install are now more likely to work. 


### Intel Compute Runtime upgrade and hardware cut-off
The `intel-compute-runtime` and `intel-igc` packages have been rebased to the latest upstream releases, providing support for new Intel hardware. However, note that these newer versions drop compute support for older Intel GPUs released prior to 2020 (gen 12 and earlier) - see [this file](https://github.com/intel/compute-runtime/blob/master/LEGACY_PLATFORMS.md) for a list of dropped architectures.

This change does not affect the `intel-media-driver` included in the default package set, which continues to have support for old generations of hardware in the main development branches for now.


### Third Party Legacy JDKs
In Fedora 42, `java` and `java-devel` package `provides` and `requires` have been adjusted to obsolote all non-system LTS JDKs. In effect, this means:

* `java-1.8.0-openjdk`, `java-11-openjdk` and `java-17-openjdk` are now *deprecated* in Fedora 39, 40, and 41. They will print a warning message upon use.
* `java-1.8.0-openjdk`, `java-11-openjdk` and `java-17-openjdk` are *retired* in Fedora 42.

Those who need these packages should use the `adoptium-temurin-java-repository` package, which enables the Adoptium Temurin repository, which in turn allows you to install the following packages:

* `temurin-8-jdk`
* `temurin-8-jre`
* `temurin-11-jdk`
* `temurin-11-jre`
* `temurin-17-jdk`
* `temurin-17-jre`
* `temurin-21-jdk`
* `temurin-21-jre`

The `adoptium-temurin-java-repository` package is available from Fedora 39 onwards.

For more detailed information, see the [Change page](https://fedoraproject.org/wiki/Changes/ThirdPartyLegacyJdks) on the Fedora Wiki. A list of known issues is available on [GitHub](https://github.com/adoptium/installer/issues/848#issuecomment-2133516101).


### Setuptools 74
Fedora 42 updates the `python3-setuptools` package to version 74.

Note that this release is not 100% compatible with previous releases. Notably, version 72.0.0 removed support for the `setup.py test` command (deprecated for 5 years). This is a breaking change and Fedora packages that use the `setup.py test` command during the build need to be adapted to use a different test runner, such as `unittest`, `pytest`, etc.

See [upstream documentation](https://setuptools.pypa.io/en/stable/history.html#v74-1-3) for information about this release.


### NumPy updated to version 2
The NumPy package has been updated from version 1.26 to 2.2.4. The update provides a large amount of improvements to the library.

See the [upstream documentation](https://numpy.org/devdocs/release/2.0.0-notes.html) for a list of changes as well as a migration guide and advice for downstream package authors. A [blogpost](https://blog.scientific-python.org/numpy/numpy2/) by the NumPy developers is also available which discusses some of the more high-level changes in the 2.x release.


### Django 5.1
The Django stack has been updated to version 5.1 in Fedora 42.

Similar to the packaging approach for the Python interpreter itself, Fedora is moving to a single source RPM for each Django major version. The major version initially shipped with a given Fedora release will have unsuffixed binary packages (e.g. `python3-django`), while any newer or older versions will have suffixed binary packages (e.g. `python3-django5`). Suffixed packages (source and binary) will only list the major version (so `python-django5` instead of `python-django5.1`). 

For information about the 5.1 release, see the [upstream release notes](https://docs.djangoproject.com/en/5.2/releases/5.1/).


### Python 3.8 retirement
The `python3.8` package will be retired without replacement from Fedora Linux 42. Python 3.8 reached upstream End of Life 2024-10-07. RHEL 8 Python 3.8 Stream has been retired since May 2023. Debian Buster had Python 3.7, Bullseye has 3.9. Ubuntu 20.04 LTS (Focal Fossa) has Python 3.8, but standard support ends in April 2025, which is when Fedora 42 releases as well. Python 3.8 was only kept in Fedora to make it possible for Fedora users to test their software against it, but with other distributions retiring it as well, this use case is no longer relevant.

Note that `python3.6` will remain available for the foreseeable future to support developers who target RHEL 8.


### Retirement of Py03 v0.19, v0.20 and v0.21 
The packages for obsolete versions of PyO3 (v0.21, v0.20, and v0.19), the Rust bindings for CPython and PyPy, were removed from Fedora. All Python packages that contain native Python extensions written in Rust are now built with PyO3 v0.22 or later, bringing official support for Python 3.13 and / or support for running on a "free-threaded" Python interpreter. 


### python-pytest-runner is now deprecated
The `python-pytest-runner` (`python3-pytest-runner`) package is deprecated in Fedora 42 due to being deprecated upstream since 2019 and the upstream repository being archived since 2023. Dependent packages are encouraged to switch to using `pytest` directly.

To migrate, follow these steps:

* Remove `pytest-runner` from your `setup_requires`, preferably removing the `setup_requires` option.
* Remove `pytest` and any other testing requirements from `tests_require`, preferably removing the `setup_requires` option.
* See [Fedora Packaging Guidelines](https://docs.fedoraproject.org/en-US/packaging-guidelines/Python/#_test_dependencies_2) for how to specify test dependencies.
* Invoke tests with `pytest`.
* Another good option is to configure a `tox.ini` next to your `setup.cfg`. https://tox.readthedocs.io/en/latest/


### Zbus v1 retirement
The packages for v1 of the `zbus` crate (and the packages for v2 of the `zvariant` crate) have been retired from Fedora 42. Dependent packages are to be ported to a non-obsolete version of these libraries (i.e. zbus v4 or v5) or to be retired as well. 

Rust library packages are not intended to be installed on end-user systems, and are almost exclusively installed in ephemeral build environments (i.e. mock chroots), so this change should not have any impact on end users.


### gtk3-rs is now deprecated
The Rust bindings for GTK3 are obsolete and officially unmaintained. The packages for them have been marked as deprecated to prevent new packages that depend on them from being added to Fedora, and they will be removed from a future release. 

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


### Changes in the Anaconda installer

You can find additional notes in the [upstream documentation](https://anaconda-installer.readthedocs.io/en/latest/release-notes.html#fedora-42).

#### Anaconda WebUI enabled by default on Workstation
Fedora 42 Workstation Edition now has a new installer user interface, based on PatternFly. It changes the previous "Hub & Spoke" model to a "Wizard" style interface with a sequence of steps that must be completed in order. It also provides a simplified built-in help in a side panel instead of the previous separate window with fully featured documentation. 

.First screen of the new UI

image::image$anaconda-1.png[Language selection in the new web UI.]

The new interface is simplified, but users who require more detailed storage configuration options can still access those in the second step of the installation ("Installation Method") using the menu button (kbd:[⋮]) in the top right corner.

.New custom partitioning screen

image::image$anaconda-2.png[New Storage Editor.]

The new user interface will be initially only be available on Fedora Workstation; other editions will follow suit in later releases.

For more information about the new interface and its development, see the [Fedora Community Blog post](https://communityblog.fedoraproject.org/anaconda-is-getting-a-new-suit-and-a-wizard/) and the [Detailed Description part of the Change page](https://fedoraproject.org/wiki/Changes/AnacondaWebUIforFedoraWorkstation#Detailed_Description) on Fedora Wiki.

#### Anaconda is now a native Wayland application
The Anaconda installer is now a native Wayland application. Previously, Anaconda operated as an Xorg application or relied on XWayland for support. By implementing this update, Anaconda can eliminate dependencies on X11 and embrace newer, more secure technologies.

Note that it is no longer possible to use TigerVNC for remote access to the GUI during the installation as TigerVNC depends on X11. Remote installations must now be performed using an application which supports the Remote Desktop Protocol (RDP) such as Gnome Remote Desktop (grd). As part of this change, the following boot options have been added: `inst.rdp`, `inst.rdp.username`, `inst.rdp.password`. The following boot options have been removed: `inst.vnc`, `inst.vncpassword`, `inst.vncconnect`. The `vnc` Kickstart command has also been removed.

#### GPT is now used by default on all architectures
Anaconda now defaults to using a GUID Partition Table (GPT) instead of a Master Boot Record (MBR) as the partition table (disklabel) on all architectures. This was previously the default on x86_64 systems, and now installations on all architectures behave the same way.


### Unofficial RISC-V images are now available
Images for the RISC-V alternative architecture with unofficial support are now available for Fedora 42 in server, cloud, and container variants. For more information, see the [announcement post on Fedora Discussion](https://discussion.fedoraproject.org/t/fedora-42-risc-v-non-official-images-are-available/148866).


### Unification of `/usr/bin` and `/usr/sbin`
In Fedora 42, the `/usr/sbin` directory becomes a symlink to `bin`, which means paths like `/usr/bin/foo` and `/usr/sbin/foo` point to the same place. `/bin` and `/sbin` are already symlinks to `/usr/bin` and `/usr/sbin`, so effectively `/bin/foo` and `/sbin/foo` also point to the same place. `/usr/sbin` will be removed from the default `$PATH`. The same change is also done to make `/usr/local/sbin` point to `/bin`, effectively making `/usr/local/bin/foo` and `/usr/local/sbin/foo` point to the same place. 

The definition of `%_sbindir` has been changed to `%_bindir`, so packages will start using the new directory after a rebuild without any further action. 

Maintainers may stop using `%_sbindir`, but don't need to.


### Plymouth: Use simpledrm by default

On Fedora 42, the boot-splash (plymouth) now defaults to using the EFI firmware framebuffer to show the boot-splash earlier during boot.

Since the EFI framebuffer does not provide the screen's DPI, plymouth now guesses whether 2x hiDPI scaling should be used or not based on the screen's resolution. So Fedora 42 may use a different scaling factor for the bootsplash than before, this only impacts the bootsplash.

The old behavior of waiting for the GPU driver to load before showing the splash can be restored by running: 

[,console]
----
sudo grubby --update-kernel=ALL --args="plymouth.use-simpledrm=0" 
----

Alternatively, the guessed hiDPI scale-factor can be overridden by running: 

[,console]
----
sudo grubby --update-kernel=ALL --args="plymouth.force-scale=1" 
----

Change `=1` to `=2` to force 2x scaling. Note if this is used the specified scale-factor will apply to all displays. 

Alternatively, instead of using the kernel commandline these settings can be configured through editing `/etc/plymouth/plymouthd.conf`. Uncomment the `[Daemon]` line and then add lines with: 

* `UseSimpledrm=1` and/or
* `DeviceScale=1` or `DeviceScale=2`

After editing `/etc/plymouth/plymouthd.conf`, the initrd must be regenerated to include the updated file by running `sudo dracut -f`. 

### `fips-mode-setup` has been removed from Fedora

The `fips-mode-setup` utility has been removed from Fedora. To operate a system in FIPS mode, you have one of the following options instead:

* Add `fips=1` to the kernel command line of the Fedora installer. On UEFI-based systems, this is typically done by pressing the `e` key while Grub displays the installer boot menu. After adding `fips=1`, press Ctrl+X to continue boot.
* Create a Fedora image using [Image Builder](https://osbuild.org/) with the following customization:
+
[,console]
----
[customizations]
fips = true
----
+
An example blueprint file to achieve this is:  
+
----
name = "fedora42-fips"
distro = "fedora-42"
description = "A Fedora image with FIPS enabled"
version = "0.0.1"
modules = []
groups = []

[customizations]
fips = true
----

* Create a disk image with [bootc](https://docs.fedoraproject.org/en-US/bootc/) and enable FIPS mode using the following instructions in the `Containerfile`:
+
----
Containerfile
FROM quay.io/fedora/fedora-bootc:42

# Enable the FIPS crypto policy
# crypto-policies-scripts is not installed by default
RUN dnf install -y crypto-policies-scripts && update-crypto-policies --no-reload --set FIPS

# Enable fips=1 kernel argument: https://bootc-dev.github.io/bootc/building/kernel-arguments.html
# This file should contain 'kargs = ["fips=1"]'
COPY 01-fips.toml /usr/lib/bootc/kargs.d/
----

Switching a system to FIPS mode after installation is no longer recommended. For example, disk encryption with LUKS, or OpenSSH key generation will make algorithmic choices during installation or first boot that are not FIPS approved when not running installation or first boot in FIPS mode.

If you still need to switch a system to FIPS mode after installation and are aware of the risks, you can add the `fips=1` argument to the kernel command line. Note that if your `/boot` is on a separate partition, you will also have to add the partition's UUID to the command line for the dracut FIPS initramfs module to be able to find the kernel and its checksum file, or the boot will fail. The following command does this in one step:

----
grubby \
  --update-kernel=ALL \
  --args="fips=1 boot=UUID=$(blkid --output value --match-tag UUID "$(findmnt --first --noheadings -o SOURCE /boot)")"
----

To disable FIPS mode, you should reinstall the system. If you need to switch an existing system — which is not recommended — you can use `grubby` again to remove the `fips=1` command line argument.


### Systemd Sysusers.d integration
The built-in rpm mechanism to create system users from `sysusers.d` metadata distributed by packages is now used to create system users, replacing the previous use of custom rpm scriptlets in individual packages.

For more information about user creation through `sysusers.d`, see the [upstream RPM documentation](https://github.com/rpm-software-management/rpm/blob/master/docs/manual/users_and_groups.md#users-and-groups).


### ComposeFS enabled by default for Fedora Atomic Desktops

On Fedora Atomic Desktop systems, the root mount of the system (`/`) is now mounted using `composefs`, which makes it a truly read only filesystem, increasing the system integrity and robustness. This is the first step toward a full at runtime verification of filesystem integrity.

This change follows a similar one in [Fedora 41](https://docs.fedoraproject.org/en-US/fedora/f41/release-notes/sysadmin/#composefs-by-default) which enabled ComposeFS by default in the Fedora CoreOS and IoT editions.


### Atomic Desktops no longer have a PPC64LE edition

Starting with Fedora 42, Fedora Atomic Desktop is no longer available for the PPC64LE (64-bit Power Little Endian) architecture due to a lack of interest. Those who want to use Atomic on such system must either revert to a Fedora package mode installation, or build their own images using Bootable Containers which are available for PPC64LE.


### Retire Zezere Provisioning Server (IoT)
Previous Fedora IoT releases used the Zezere provisioning server for initial configuration. However, this approach caused problems for some users, notably those using IPv6. Starting with Fedora 42, Zezere has been replaced with `systemd-firstboot`. Users who have been unable to use Zezere will have an easier and more straightforward way to configure their system, resulting in less frustration during the critical first boot experience. 

The Getting Started section of the [Fedora IoT documentation](https://docs.fedoraproject.org/en-US/iot/ignition/) has been updated to reflect this change.


### Fedora CoreOS updates moved from OSTree to OCI
Fedora CoreOS now receives updates from [OCI registry](https://quay.io/repository/fedora/fedora-coreos) instead of the Fedora OSTree repository. The old OSTree repository will continue to be active until Fedora 43 release. Disk images will be updated first, so new installations of Fedora 42-based Fedora CoreOS will use OCI images from the start. Existing nodes will be migrated in the future.

This change helps align Fedora CoreOS with the ongoing [Bootable Containers](https://docs.fedoraproject.org/en-US/bootc/getting-started/#_what_is_a_bootable_container) initiative.


### Distributing Kickstart Files as OCI Artifacts
Fedora distributed as bootable container ships via [OCI registry](https://quay.io/repository/fedora/fedora-bootc?tab=tags). Installation is typically done by conversion into a VM image or ISO installer via [osbuild](https://osbuild.org/) (image builder), however, booting from network is a useful workflow for bare-metal fleet deployments. Required files to perform such installation were previously not available in the OCI repository that could be fetched from registry in a similar manner as the bootable container. This changes in Fedora 42.

Previously, Kickstart files were only available in the Fedora RPM repository and it could be cumbersome to find appropriate RPM repository version and extract needed files instead of fetching all the needed assets from the registry only. Fedora 42 introduces an OCI repository with the files in question for each Fedora stable version. 

Kickstart files will also continue to be distributed in RPM repositories.

See the [Change page](https://fedoraproject.org/wiki/Changes/KickstartOciArtifacts) on the Fedora Wiki for more information.


### Fedora WSL Images

Fedora now provides WSL (Windows Subsystem for Linux) images. They are available for download on the [Getfedora cloud page](https://fedoraproject.org/cloud/download).

WSL is a Windows subsystem that allows Windows users to easily run multiple guest Linux distributions as containers inside a single virtual machine managed by a Windows host. 

The Fedora base container can already be used with WSL, but it is not ideal as it intentionally excludes documentation and non-essential tools, which this cloud image provides.

For documentation on how to use these images, see [Fedora Cloud docs](https://docs.fedoraproject.org/en-US/cloud/).


### Ansible 11

In this Fedora release the `ansible` package has been upgraded to version 11. There are many changes and for a full list of them see the [upstream documentation]( https://docs.ansible.com/ansible/latest/roadmap/COLLECTIONS_11.html).

Also, the `ansible-core` package has been upgraded to version 2.18. Some of the notable changes include:

* Dropped Python 3.10, and added Python 3.13 for controller code.
* Dropped Python 3.7, and added Python 3.13 for target code.
* Added the break functionality for task loops.
* Added new non-local mount facts.

For more details see the [upstream documentation](https://docs.ansible.com/ansible/latest/roadmap/ROADMAP_2_18.html).


### General Intel SGX enablement

Intel Software Guard Extensions (SGX) is a piece of technology that enables creation of execution enclaves. Their memory is encrypted and thus protected from all other code running on the CPU, including System Management Mode (SMM), firmware, the kernel and user space.

This Fedora update provides the SGX host software stack, architectural enclaves and development packages. The change focuses on *general* software infrastructure enablement. The aim is to introduce applications and features in the future, which will have a dependency on SGX. 


### Managing expired PGP keys in DNF5
Fedora 42 introduces a new way to handle installing RPM packages from repositories while outdated PGP keys are present in the system. Previously, such keys had to be removed manually by running `rpmkeys --delete`. Starting with this release, expired keys will be detected automatically before any DNF transaction and handled appropriately using a new libDNF5 plugin which is enabled by default.

For those using interactive mode, a prompt will now appear informing them about each outdated key on the system and asking for confirmation to remove it. For non-interactive users, there will be no change to the workflow. 


### Fedora supports Copy on Write functionality

This update improves the way software packages are downloaded and installed on Fedora. The change provides a better experience for users as it reduces the amount of I/O resources required and offsets the CPU cost of package decompression. As a result, the OS installs and upgrades the packages faster.

New package installation process::
. Resolve packaging request into a list of packages and operations.
. Download and *decompress* packages into a *locally optimized* `rpm` file.
. Install and/or upgrade packages sequentially using the `rpm` files. The process uses *reference linking* (reflinking) to reuse data that is already on the disk.

Note that this behavior is not being turned on by default, and thus it is explicitly opt-in for now.


### Stratis 3.8: stratisd 3.8.0 and stratis-cli 3.8.0
Stratis 3.8.0, which consists of `stratisd 3.8.0` and `stratis-cli 3.8.0`
includes two significant enhancements, as well as a number of minor
improvements.

Most significantly, Stratis 3.8.0 introduces a revised storage stack. The
motivation for this change and overall structure of the storage stack is
described [in a separate post](https://stratis-storage.github.io/metadata-rework).

Stratis 3.8.0 also introduces support for multiple bindings for encryption
using the same mechanism. Previously, Stratis only allowed a single binding
that used a key in the kernel keyring, now multiple bindings with different
keys may be used for the same pool. Similarly, multiple bindings that make
use of a Clevis encryption mechanism may be used with the same pool. The
number of total bindings is limited to 15.

This change enables a number of use cases that the previous scheme did not
allow. For example, a pool might be configured so that it can be unlocked
with one key belonging to a storage administrator, for occasional necessary
maintenance, and with a different key by the designated user of the pool.

Previously, when starting an encrypted pool, the user was required to
designate an unlock method, `clevis` or `keyring`. Since this release
allows multiple bindings with one unlock method, it introduces a more general
method of specifying an unlock mechanism on pool start. The user may specify
`--unlock-method=any` and all available methods may be tried. The user
may also specify that the pool should be opened with one particular binding,
using the `--token-slot` option. Or the user may choose to enter a passphrase
to unlock the pool instead, either by specifying the `--capture-key` option
or a keyfile using the `--keyfile-path` option. Similarly, the `unbind`
command now requires the user to specify which binding to unbind using the
`--token-slot` option. And the rebind method requires that the user specify
a particular token slot with the `--token-slot` option if the pool has more
than one binding with the same method.

There were also a number of internal improvements, minor bug fixes, and
dependency updates.

Please consult the [stratisd](https://github.com/stratis-storage/stratisd/blob/master/CHANGES.txt)
and [stratis-cli](https://github.com/stratis-storage/stratis-cli/blob/master/CHANGES.txt)
changelogs for additional information about the release.


### ZlibNG 2.2
The `zlib-ng` data compression library in Fedora 42 has been updated to version 2.2, specifically 2.2.4. The updated version provides new optimizations, rewrites deflate memory allocation, and improves the build systems and tests.

You can find release notes for version 2.2 at the following links:

* https://github.com/zlib-ng/zlib-ng/releases/tag/2.2.0
* https://github.com/zlib-ng/zlib-ng/releases/tag/2.2.1
* https://github.com/zlib-ng/zlib-ng/releases/tag/2.2.2
* https://github.com/zlib-ng/zlib-ng/releases/tag/2.2.3
* https://github.com/zlib-ng/zlib-ng/releases/tag/2.2.4


### Trafficserver 10.0
Apache Traffic Server (trafficserver) in Fedora has been upgraded to version 10.x. The `/etc/trafficserver/records.config` file will be automatically updated to the new `records.yaml` format. Additional upgrade steps may be required if removed features or APIs are in use; please review the [upstream documentation](https://docs.trafficserver.apache.org/en/10.0.x/release-notes/upgrading.en.html).


### Bpfman added to Fedora
Fedora 42 provides the bpfman package. 

Bpfman is a software stack simplifying the management of eBPF programs in Kubernetes clusters or on individual hosts. It comprises a system daemon (`bpfman`), eBPF Custom Resource Definitions (CRDs), an agent (`bpfman-agent`), and an operator (`bpfman-operator`). Developed in Rust on the Aya library, bpfman offers improved security, visibility, multi-program support, and enhanced productivity for developers.

For Fedora, integrating bpfman would streamline eBPF program loading. It enhances security by restricting privileges to the controlled bpfman daemon, simplifies deployment in Kubernetes clusters, and offers improved visibility into running eBPF programs. This integration aligns with Fedora's commitment to providing efficient and secure solutions, making it easier for users to leverage the benefits of eBPF in their systems. 


### Firewalld IPv6_rpfilter now defaults to `loose` on Workstations
Fedora Workstation variants use connectivity checks by default. These checks can fail for multi-homed (e.g. LAN + Wi-Fi) hosts where firewalld uses `IPv6_rpfilter=strict`. Therefore, starting in Fedora 42, Fedora Workstation now defaults to `IPv6_rpfilter=loose` to allow connectivity checks to function as intended. 

For systems upgrading to Fedora 42, the new value of `IPv6_rpfilter` depends on whether the user has customized `/etc/firewalld/firewalld.conf`. If not, then the RPM upgrade process will update the configuration to `IPv6_rpfilter=loose.` If yes, then the existing configuration will be retained.

Note that this change is a deviation from firewalld upstream, which continues to default to `IPv6_rpfilter=strict`.


### cockpit-navigator replaced with cockpit-files
Fedora 42 replaces the Cockpit Navigator plugin with Cockpit Files. Last year the Cockpit project released a new officially supported Cockpit Files plugin intended to provide a modern alternative to the existing Cockpit navigator plugin. The latest release (14) supports everything which Cockpit navigator did except the creation of symlinks which is planned to be implemented. 

Replacing `cockpit-navigator` with `cockpit-files` leads to a visual change within Cockpit: the Navigator menu entry will be replaced with a new File browser menu entry under Tools. 

The UI of `cockpit-files` is different from `cockpit-navigator` but offers the same functionality with the exception of symlink creation. `cockpit-files` uses PatternFly as UI toolkit, making the user experience more consistent. 


### Confidential Virtualization Host with AMD SEV-SNP
Fedora 42 enables virtualization hosts to launch confidential virtual machines using AMD's SEV-SNP technology. Confidential virtualization prevents admins with root shell access, or a compromised host software stack, from accessing memory of any running guest. SEV-SNP is an evolution of previously provided SEV and SEV-ES technologies providing stronger protection and unlocking new features such as a secure virtual TPM. 


### Optimized binaries for the x86_64 architecture
Fedora now provides a mechanism for automatically loading binaries optimized for newer versions of the x86_64 architecture using `glibc-hwcaps`. Users may notice faster execution times for binaries where the package maintainer opted in to use this mechanism. For a full explanation, see the [Change page](https://fedoraproject.org/wiki/Changes/Optimized_Binaries_for_the_AMD64_Architecture_v2) on the Fedora Wiki.


### Retirement of PostgreSQL 15

PostgreSQL version 15 will be retired from Fedora 42 since there are newer versions (16 and 17). Version 16 is already the default version (announced in PostgreSQL 16 change), and version 17 would be the alternative. 

If you still have not upgraded to the default stream 16, you should follow the standard upgrade strategy:

Dump and restore upgrade::
. Stop the `postgresql` service
. Dump the databases using `su - postgres -c "pg_dumpall > /PATH/TO/pgdump_file.sql"`
. Backup all of the data in `/var/lib/pgsql/data/`
. Enumerate all postgresql-based packages by `rpm -qa | grep postgresql`
. Upgrade all installed (enumerated in the previous step) PostgreSQL packages using (e.g. for upgrading to PG-16) `dnf install PACKAGE_NAMES --allowerasing`
. Copy the old configuration files to the `/var/lib/pgsql/data/`
. Start the `postgresql` service
. Import data from the dumped file using `su - postgres -c 'psql -f /PATH/TO/pgdump_file.sql postgres'`

Fast upgrade using `pg_upgrade`::
. Stop the `postgresql` service
. Backup all of the data in `/var/lib/pgsql/data/`
. Enumerate all postgresql-based packages by `rpm -qa | grep postgresql`
. Upgrade all installed (enumerated in the previous step) PostgreSQL packages using (e.g. for upgrading to PG-16) `dnf install PACKAGE_NAMES --allowerasing`
. Install the upgrade package `dnf install postgresql-upgrade`
. Run `postgresql-setup --upgrade`
. Copy the old configuration files to the `/var/lib/pgsql/data/`
. Start the `postgresql` service


### OpenDMARC split into multiple packages
The `opendmarc` package previously included a set of optional supporting binaries which are not required to configure the service, which caused them to pull a high number (80+) additional packages as dependencies. Starting with Fedora 42, the `opendmarc` package only contains core utilities, and additional tools can be installed separately if needed, potentially saving space for those who don't need them. The new separate packages are:

* `opendmarc-check`
* `opendmarc-expire`
* `opendmarc-import`
* `opendmarc-importstats`
* `opendmarc-params`
* `opendmarc-reports`


### Packages requiring the `git` binary now depend on the `git-core` package

Previously, the `git` package was complex, divided into multiple sub-packages, and was providing the `git` binary. If you wanted to satisfy those packages that required the `git` binary, you experienced a long and computationally intensive installation process. With this update, the `git` binary is now provided through the `git-core` package, which should reduce the amount of packages installed as a transient dependency of the main package.


### Live media now use the EROFS filesystem instead of SquashFS
Fedora Linux live environments now use the Enhanced Read-Only FileSystem (EROFS), a modern, feature-rich read-only filesystem. 


### `pam_ssh_agent_auth` removed from Fedora
The [`pam_ssh_agent_auth`](https://packages.fedoraproject.org/pkgs/openssh/pam_ssh_agent_auth/) package has been removed in Fedora 42 due to being outdated and rarely used.

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
