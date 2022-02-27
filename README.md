# Simple script to set the debuggable attribute to true in an Android apk package

## Usage

### XML-only

`py makeDebuggable.py xml [file in] [file out]`

This takes an existing AndroidManifest.xml file and outputs a version where debuggable is set to true.

### APK

`py makeDebuggable.py apk [file in] [file out] [keystore] [key alias]`

_This command requires zipalign and apksigner present in PATH. You can get them by installing `platform-tools` using [sdkmanager](https://developer.android.com/studio/command-line/sdkmanager)._

This reads an existing APK file and outputs a version where debuggable is set to true. The last two arguments are for apksigner and define the JKS keystore location and the key alias for re-signing the apk.

## Notes on other tools

There exist other much more powerful tools like androguard or apktool, but in order to patch the debuggable attribute, they all need to at least decode the full AndroidManifest.xml.

This tool is designed to make as few changes to the overall binary as possible in order to decrease the chance of encountering de-/encoding issues e.g. through APK obfuscation.
