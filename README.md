# Simple script to set the debuggable attribute to true in an Android apk package

## Usage

### XML-only

`./makeDebuggable.py xml [file in] [file out]`

This takes an existing AndroidManifest.xml file and outputs a version where debuggable is set to true.

### APK

`./makeDebuggable.py apk [fileIn] [fileOut] [keystore] [key alias] [keystore password]`

_This command requires zipalign and apksigner present in PATH. You can get them by installing `platform-tools` using [sdkmanager](https://developer.android.com/studio/command-line/sdkmanager)._

This reads an existing APK file and outputs a version where debuggable is set to true. The last two arguments are for apksigner and define the JKS keystore location and the key alias for re-signing the apk and the password for the keystore.

### Running in Docker

If you have Docker installed, you can use it to run this tool completely separated from your system:

```
docker build -t makedebuggable --build-arg UID=`id -u` --build-arg GID=`id -g` .
docker run -it --rm -v $PWD:/home/makedebuggable -u makedebuggable makedebuggable ./keygen.sh
docker run -it --rm -v $PWD:/home/makedebuggable -u makedebuggable makedebuggable ./makeDebuggable.py apk mullvad.apk mullvad-debug.apk debuggable.keystore debuggable pwpwpw
```

In this example, we also generate a new keystore for handling the signature requirement of APKs. You only need to do this, if you are working on an APK, for which you don't have the original private key. If you want to use your own keystore, just move it to the current directory.

Please note, that if you change the signing key of an APK, the resulting APK can only be installed on an Android device, if the previous APK is deleted first, this will destroy your user data for that app. Therefore it's advisable, that you backup the output of `keygen.sh`, maybe later you want to sign new versions of the APK.

## Notes on other tools

There exist other much more powerful tools like androguard or apktool, but in order to patch the debuggable attribute, they all need to at least decode the full AndroidManifest.xml.

This tool is designed to make as few changes to the overall binary as possible in order to decrease the chance of encountering de-/encoding issues e.g. through APK obfuscation.
