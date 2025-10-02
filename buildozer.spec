[app]
# (str) Title of your application
title = SpeechTranslator

# (str) Package name
package.name = speechtranslator

# (str) Package domain (reverse DNS)
package.domain = org.example

# (str) Source code where the main.py is located
source.dir = .

# (list) List of inclusions using pattern matching
source.include_exts = py,kv,png,jpg,txt

# (str) Application versioning
version = 1.0

# (list) Application requirements
# NOTE: including 'sarvamai' may require additional native recipes. If you face build errors,
# remove sarvamai from requirements and instead upload to your server from the app (requests).
requirements = python3,kivy,pyjnius,requests,sounddevice,soundfile

# (str) Icon of the app
icon.filename = %(source.dir)s/icon.png

# (str) Supported orientation (portrait/landscape)
orientation = portrait

# (list) Permissions
android.permissions = RECORD_AUDIO, INTERNET, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE

# (int) Minimum API your app will support
android.minapi = 21

# (int) Android SDK target (build tools)
android.sdk = 33

# (str) Android entry point, don't change
android.entrypoint = org.kivy.android.PythonActivity

# (int) Android NDK version to use (optional)
#android.ndk = 23b

# (str) Presplash / other settings omitted for brevity

[buildozer]
log_level = 2
warn_on_root = 1
