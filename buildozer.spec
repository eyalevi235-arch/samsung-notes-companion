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

# (list) List of inclusions using pattern matching
#source.include_patterns = assets/*,images/*.png

# (list) Source files to exclude (leave empty to not exclude anything)
source.exclude_exts = spec

# (list) List of directory names to exclude
source.exclude_dirs = tests, bin, venv, .git, .github, .buildozer

# (str) Application versioning (method 1)
version = 0.1

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,kivy==2.3.0

# (str) Supported orientation (landscape, sensorLandscape, portrait or all)
orientation = landscape

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# (int) Target Android API, should be as high as possible.
#android.api = 33

# (int) Minimum API your APK will support.
#android.minapi = 21

# (str) Android NDK version to use
android.ndk = 25b

# (bool) Accept Android SDK license
android.accept_sdk_license = True

# (str) python-for-android branch to use
p4a.branch = master

# (str) The Android archs to build for, comma separated
android.archs = arm64-v8a, armeabi-v7a

# (bool) enables Android auto backup feature (Android API >=23)
android.allow_backup = True

# (str) The format used to package the app for release
#android.release_artifact = aab

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug)
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
