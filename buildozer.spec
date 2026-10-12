[app]

# (str) Title of your application
title = Samsung Notes Companion

# (str) Package name
package.name = samsungnotescompanion

# (str) Package domain (needed for android packaging)
package.domain = org.samsungnotes

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include (leave empty to include all the files)
source.include_exts = py,png,jpg,jpeg,atlas,kv,pdf

# (list) Source files to exclude (leave empty to not exclude anything)
source.exclude_exts = spec

# (list) List of directory names to exclude
source.exclude_dirs = tests, bin, venv, .git, .github, .buildozer, __pycache__

# (str) Application versioning (method 1)
version = 1.4

# (list) Application requirements
# Kivy 2.3.1 supports Cython 0.29.x through 3.0.11 on Python 3.10.
requirements = python3,kivy==2.3.1,pillow==10.4.0,pyjnius,android,pypdf==4.3.1

# (list) Supported orientations for Buildozer 1.5.0
# Valid options: landscape, portrait, portrait-reverse, landscape-reverse
orientation = portrait, landscape

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,READ_MEDIA_IMAGES

# (int) Target Android API (stable with NDK 25b / p4a master)
android.api = 33

# (int) Minimum API your APK will support
android.minapi = 21

# (int) Android NDK API (must be <= android.api and >= 21)
android.ndk_api = 21

# (str) Android NDK version to use (p4a master currently supports NDK 25.x)
android.ndk = 25b

# (bool) Accept Android SDK license (required for CI)
android.accept_sdk_license = True

# (str) python-for-android fork/branch (master is the stable line for Python 3.10)
p4a.fork = kivy
p4a.branch = master

# Do not force setup.py integration; Kivy recipes expect --ignore-setup-py.
p4a.setup_py = false

# (str) Bootstrap to use for android builds
p4a.bootstrap = sdl2

# Samsung devices are arm64; a single arch avoids the armeabi-v7a libffi/NDK failures
# and roughly halves GitHub Actions compile time.
android.archs = arm64-v8a

# (bool) enables Android auto backup feature (Android API >=23)
android.allow_backup = True

# Needed so the system document picker (My Files / Drive) can return a URI.
android.enable_androidx = True

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug)
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 0
