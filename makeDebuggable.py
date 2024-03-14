#!/usr/bin/env python3


# parsing information from
# https://cs.android.com/android/platform/superproject/+/master:frameworks/base/libs/androidfw/include/androidfw/ResourceTypes.h

from io import BytesIO, SEEK_CUR
import os
import sys
from struct import pack, unpack
from zipfile import ZipFile
import subprocess
from shutil import which

COMMON_HEADER_LEN = 8
CHUNK_TYPE_STRINGPOOL = 0x1
CHUNK_TYPE_RESMAP = 0x180
CHUNK_TYPE_START_ELEMENT = 0x0102
DEBUGGABLE_RES_ID = 0x0101000f
DEBUGGABLE_STRING = "debuggable"
DEBUGGABLE_STRING_LENGTH_UTF8 = 12 # 1 + 10 + 1
DEBUGGABLE_STRING_LENGTH_UTF16 = 24 # 2 + 10*2 + 2
DEBUGGABLE_STRING_DATA_UTF8 = bytearray([10, 100, 101, 98, 117, 103, 103, 97, 98, 108, 101, 0])
DEBUGGABLE_STRING_DATA_UTF16 = bytearray([10, 0, 100, 0, 101, 0, 98, 0, 117, 0, 103, 0, 103, 0, 97, 0, 98, 0, 108, 0, 101, 0, 0, 0])
ANDROID_NS_STRING = "http://schemas.android.com/apk/res/android"
APPLICATION_STRING = "application"
UINT32_LENGTH = 4
UINT16_LENGTH = 2
UINT8_LENGTH = 1
DEBUGGABLE_VALUE_TRUE = bytearray([0xFF, 0xFF, 0xFF, 0xFF])
ATTRIBUTE_LENGTH = 20

# UTIL
def dumpN(buf, n):
    l = buf.tell()
    print([hex(el) for el in buf.read(n)])
    buf.seek(l)

def readInt(f, n):
    return readType(f, n, "I", UINT32_LENGTH)

def readShort(f, n):
    return readType(f, n, "H", UINT16_LENGTH)

def readByte(f, n):
    return readType(f, n, "B", UINT8_LENGTH)

def readType(f, n, fmtType, typeLen):
    fmt = "<" + str(n) + fmtType
    data = unpack(fmt, f.read(n * typeLen))
    if n == 1:
        return data[0]
    else:
        return data

def isInt32NotNegative(v):
    return ((1 << 31) & v) == 0

def dumpStrPool(fIn, strPoolInfo):
    pos = fIn.tell()
    for i in range(strPoolInfo["stringCount"]):
        print(i, readString(fIn, strPoolInfo, i))
    fIn.seek(pos)

def dumpResmap(fIn, resmapInfo):
    pos = fIn.tell()
    fIn.seek(resmapInfo["chunkInfo"]["startOffset"] + COMMON_HEADER_LEN)
    for i in range(resmapInfo["len"]):
        print(i, hex(readInt(fIn, 1)))
    fIn.seek(pos)

def readCommonHeader(fs):
    data = fs.read(COMMON_HEADER_LEN)
    if len(data) < COMMON_HEADER_LEN:
        if len(data) > 0:
            print("Skipping last " + str(len(data)) + " bytes")
        return None
    type, headerSize, size = unpack("<HHI", data)
    return {
        "type": type,
        "headerSize": headerSize,
        "chunkSize": size
    }

def writeCommonHeader(f, type, headerSize, size):
    f.write(pack("<HHI", type, headerSize, size))

def readChunks(inStream):
    chunk = []
    currPos = inStream.tell()
    while header := readCommonHeader(inStream):
        chunk.append({
            "startOffset": currPos,
            "commonHeader": header
        })
        inStream.seek(header["chunkSize"] - COMMON_HEADER_LEN, SEEK_CUR)
        currPos = inStream.tell()
    return chunk

def findStringpoolAndResmap(chunks):
    stringPoolIdx = -1
    resmapIdx = -1
    for i, chunkInfo in enumerate(chunks):
        chunkType = chunkInfo["commonHeader"]["type"]
        if chunkType == CHUNK_TYPE_STRINGPOOL:
            if stringPoolIdx >= 0:
                raise Exception("More than one string pool!")
            stringPoolIdx = i
        elif chunkType == CHUNK_TYPE_RESMAP:
            if resmapIdx >= 0:
                raise Exception("More than one resmap!")
            resmapIdx = i
    if stringPoolIdx < 0:
        raise Exception("No string pool found!")
    return (stringPoolIdx, resmapIdx)

def decodeStringPoolInfo(f, chunkInfo):
    offset = chunkInfo["startOffset"]
    f.seek(offset + COMMON_HEADER_LEN)
    (stringCount, styleCount, flags, stringsStart, stylesStart) = readInt(f, 5)
    return {
        "chunkInfo": chunkInfo,
        "stringCount" : stringCount,
        "styleCount": styleCount,
        "flags": flags,
        "stringsStart": stringsStart,
        "stylesStart": stylesStart,
        "isUtf8": (flags & (1 << 8)) != 0
    }

# inserts "debuggable" string at insertionIdx
# requires that insertionIdx < stringCount
# todo: update styles (first is str ref)
def patchStringPool(f, strPoolInfo, fOut, insertionIdx):
    startOffset = strPoolInfo["chunkInfo"]["startOffset"]
    f.seek(startOffset + COMMON_HEADER_LEN) # we write a new common header
    isUtf8 = strPoolInfo["isUtf8"]
    debuggableStrLength = DEBUGGABLE_STRING_LENGTH_UTF8 if isUtf8 else DEBUGGABLE_STRING_LENGTH_UTF16
    newStrCount = strPoolInfo["stringCount"] + 1
    newStringsStart = strPoolInfo["stringsStart"] + UINT32_LENGTH
    newStylesStart = 0
    if strPoolInfo["styleCount"] > 0:
        newStylesStart = strPoolInfo["stylesStart"] + UINT32_LENGTH + debuggableStrLength
    newChunkSize = strPoolInfo["chunkInfo"]["commonHeader"]["chunkSize"] + debuggableStrLength + UINT32_LENGTH
    writeCommonHeader(fOut, strPoolInfo["chunkInfo"]["commonHeader"]["type"], strPoolInfo["chunkInfo"]["commonHeader"]["headerSize"], newChunkSize)
    fOut.write(pack("<5I", newStrCount, strPoolInfo["styleCount"], strPoolInfo["flags"], newStringsStart, newStylesStart))

    # now we need to patch the string offset table
    f.seek(startOffset + strPoolInfo["chunkInfo"]["commonHeader"]["headerSize"])
    fOut.write(f.read((insertionIdx) * UINT32_LENGTH)) # copy up to insertionIdx, offsets havent changed up to here
    insertionStringsOffset = readInt(f, 1) # we need this later
    fOut.write(pack("<I", insertionStringsOffset))
    fOut.write(pack("<I", insertionStringsOffset + debuggableStrLength))

    # now, copy the remaining offsets but add debuggableStrLength to all of them
    for i in range(insertionIdx + 1, strPoolInfo["stringCount"]):
        fOut.write(pack("<I", readInt(f, 1) + debuggableStrLength))

    if f.tell() != startOffset + strPoolInfo["chunkInfo"]["commonHeader"]["headerSize"] + UINT32_LENGTH * strPoolInfo["stringCount"]:
        raise Exception("sanity check {} {}".format(f.tell(), startOffset + strPoolInfo["chunkInfo"]["commonHeader"]["headerSize"] + UINT32_LENGTH * strPoolInfo["stringCount"]))

    # write style index table if there is any
    if strPoolInfo["styleCount"] > 0:
        fOut.write(f.read(strPoolInfo["styleCount"] * UINT32_LENGTH))

    # in case there is some padding, copy that too
    fOut.write(f.read(startOffset + strPoolInfo["stringsStart"] - f.tell()))

    # copy the first strings up to the point where 'debuggable' gets inserted
    fOut.write(f.read(insertionStringsOffset))

    # insert new string
    fOut.write(DEBUGGABLE_STRING_DATA_UTF8 if isUtf8 else DEBUGGABLE_STRING_DATA_UTF16)

    if strPoolInfo["styleCount"] > 0:
        # copy up to styleStart
        fOut.write(f.read(startOffset + strPoolInfo["stylesStart"] - f.tell()))
        # copy styles
        for i in range(strPoolInfo["styleCount"]):
            (name, firstChar, lastChar) = unpack(readInt(f, 3))
            if name != 0xFFFFFFFF and name >= insertionIdx:
                name += 1
            fOut.write(pack("<3I", name, firstChar, lastChar))

    fOut.write(f.read(startOffset + strPoolInfo["chunkInfo"]["commonHeader"]["chunkSize"] - f.tell()))

def calculateResMapLength(chunkInfo):
    return (chunkInfo["commonHeader"]["chunkSize"] - chunkInfo["commonHeader"]["headerSize"]) // UINT32_LENGTH

def findDebuggablResIndices(f, resmapInfo):
    if resmapInfo["chunkInfo"] == None:
        return [] # chunk is empty

    startPos = resmapInfo["chunkInfo"]["startOffset"]
    f.seek(startPos + resmapInfo["chunkInfo"]["headerSize"])
    indices = []

    for i in range(resmapInfo["len"]):
        resId = readInt(f, 1)
        if resId == DEBUGGABLE_RES_ID:
            indices.append[i]

    return indices

# following three methods are mostly copied from androguard

def decode8(fs):
    # UTF-8 Strings contain two lengths, as they might differ:
    # 1) the UTF-16 length
    (str_len, bytesRead) = decodeLength(fs, 1) # todo assert equals length

    # 2) the utf-8 string length
    (strBytes, bytesRead2) = decodeLength(fs, 1)

    str = fs.read(strBytes).decode("utf-8", "replace")
    if fs.read(1) != b"\x00":
        raise Exception("String '{}' not terminated by NULL".format(str))

    return (str, bytesRead + bytesRead2 + strBytes + 1)

def decode16(fs):
    (str_len, bytesRead) = decodeLength(fs, 2)

    # The len is the string len in utf-16 units
    strBytes = str_len * 2

    str = fs.read(strBytes).decode("utf-16", "replace")
    if fs.read(2) != b"\x00\x00":
        raise Exception("String '{}' not terminated by NULL".format(str))
    return (str,  bytesRead + strBytes + 2)

def decodeLength(fs, sizeof_char):
        fmt = "<2{}".format('B' if sizeof_char == 1 else 'H')
        highbit = 0x80 << (8 * (sizeof_char - 1))

        length1, length2 = unpack(fmt, fs.read(sizeof_char * 2))

        if (length1 & highbit) != 0:
            length = ((length1 & ~highbit) << (8 * sizeof_char)) | length2
            bytesRead = sizeof_char * 2
        else:
            length = length1
            fs.seek(-sizeof_char, SEEK_CUR) # go back a char
            bytesRead = sizeof_char

        # These are true asserts, as the size should never be less than the values
        if sizeof_char == 1:
            assert length <= 0x7FFF, "length of UTF-8 string is too large!"
        else:
            assert length <= 0x7FFFFFFF, "length of UTF-16 string is too large!"

        return (length, bytesRead)

def readString(f, strPoolInfo, idx):
    pos = f.tell() # todo: find more elegant solution that requires less seeking, maybe copy whole file in mem?
    if not isInt32NotNegative(idx) or idx >= strPoolInfo["stringCount"]:
        return None
    # overall file offset to the location where the offset within the strings blob is stored
    stringOffsetsTableOffset = strPoolInfo["chunkInfo"]["startOffset"] + strPoolInfo["chunkInfo"]["commonHeader"]["headerSize"]
    f.seek(stringOffsetsTableOffset + idx*UINT32_LENGTH)
    stringOffset = readInt(f, 1)
    stringAbsoluteOffset = strPoolInfo["chunkInfo"]["startOffset"] + strPoolInfo["stringsStart"] + stringOffset
    f.seek(stringAbsoluteOffset)
    strVal = decode8(f)[0] if strPoolInfo["isUtf8"] else decode16(f)[0]
    f.seek(pos)
    return strVal

def findApplication(f, chunks, strPoolInfo):
    applicationIdx = -1
    for i, chunkInfo in enumerate(chunks):
        chunkType = chunkInfo["commonHeader"]["type"]
        if chunkType != CHUNK_TYPE_START_ELEMENT:
            continue
        f.seek(chunkInfo["startOffset"] + chunkInfo["commonHeader"]["headerSize"] + 4) # +4 to skip NS
        nameId = readInt(f, 1)
        name = readString(f, strPoolInfo, nameId)
        if name != APPLICATION_STRING:
            continue
        if applicationIdx >= 0:
            raise Exception("Multiple application elements!")
        applicationIdx = i
    if applicationIdx < 0:
        raise Exception("No application element found!")
    return applicationIdx

def decodeAttributes(f, applicationChunk):
    chunkDataStart = applicationChunk["startOffset"] + applicationChunk["commonHeader"]["headerSize"]
    f.seek(chunkDataStart + 8) # +8 to skip ns and name
    (attributeStart, attributeSize, attributeCount, idIndex, classIndex, styleIndex) = readShort(f, 6)
    if attributeSize != ATTRIBUTE_LENGTH:
        raise Exception("Cannot decode attribute length != {}!".format(ATTRIBUTE_LENGTH))
    f.seek(chunkDataStart + attributeStart)
    attrs = []
    for _ in range(attributeCount):
        attrOffset = f.tell()
        (ns, name, rawVal, size, _, dataType, data) = unpack("<IIIHBBI", f.read(ATTRIBUTE_LENGTH))
        attrs.append({
            "startOffset": attrOffset,
            "nsId": ns,
            "nameId": name,
            "rawVal": rawVal,
            "size": size,
            "dataType": dataType,
            "data": data
        })
    return attrs

def readResId(f, resmapInfo, idx):
    if idx >= resmapInfo["len"]:
        return None
    pos = f.tell()
    f.seek(resmapInfo["chunkInfo"]["startOffset"] + resmapInfo["chunkInfo"]["commonHeader"]["headerSize"] + idx * UINT32_LENGTH)
    resId = readInt(f, 1)
    f.seek(pos)
    return resId

def patchResmap(f, resmapInfo, fOut):
    f.seek(resmapInfo["chunkInfo"]["startOffset"] + COMMON_HEADER_LEN)
    newChunkSize = resmapInfo["chunkInfo"]["commonHeader"]["chunkSize"] + UINT32_LENGTH # new res id
    writeCommonHeader(fOut, resmapInfo["chunkInfo"]["commonHeader"]["type"], resmapInfo["chunkInfo"]["commonHeader"]["headerSize"], newChunkSize)
    toCopy = resmapInfo["chunkInfo"]["commonHeader"]["chunkSize"] - COMMON_HEADER_LEN # common header already written
    fOut.write(f.read(toCopy))
    fOut.write(pack("<I", DEBUGGABLE_RES_ID))

def injectResmap(fOut):
    writeCommonHeader(fOut, CHUNK_TYPE_RESMAP, COMMON_HEADER_LEN, COMMON_HEADER_LEN + UINT32_LENGTH)
    fOut.write(pack("<I", DEBUGGABLE_RES_ID))

def findDebuggableAttribute(f, strPoolInfo, resmapInfo, attrs):
    for i, attr in enumerate(attrs):
        nameId = attr["nameId"]
        name = readString(f, strPoolInfo, nameId)
        resId = readResId(f, resmapInfo, nameId)
        if name == DEBUGGABLE_STRING and resId == DEBUGGABLE_RES_ID:
            return i
    return -1

def patchStringRef(fIn, fOut, cmp):
    n = readInt(fIn, 1)
    if n != 0xFFFFFFFF and n >= cmp:
        n += 1
    fOut.write(pack("<I", n))

def patchNode(fIn, fOut, debuggableStringId):
    fOut.write(fIn.read(UINT32_LENGTH)) # lineNo
    patchStringRef(fIn, fOut, debuggableStringId) # comment

def patchCDataExt(fIn, fOut, debuggableStringId):
    patchStringRef(fIn, fOut, debuggableStringId) # data
    fOut.write(fIn.read(2*UINT32_LENGTH)) # typedData

def patchNamespaceExt(fIn, fOut, debuggableStringId):
    patchStringRef(fIn, fOut, debuggableStringId) # prefix
    patchStringRef(fIn, fOut, debuggableStringId) # uri

def patchEndElementExt(fIn, fOut, debuggableStringId):
    patchStringRef(fIn, fOut, debuggableStringId) # ns
    patchStringRef(fIn, fOut, debuggableStringId) # name

def patchAttrExt(fIn, fOut, chunkInfo, debuggableStringId):
    startOffset = chunkInfo["startOffset"]
    end = startOffset + chunkInfo["commonHeader"]["chunkSize"]
    patchStringRef(fIn, fOut, debuggableStringId) # ns
    patchStringRef(fIn, fOut, debuggableStringId) # name
    (attrStart, attrSize, currAttrCount) = readShort(fIn, 3)
    fOut.write(pack("<HHH", attrStart, attrSize, currAttrCount))
    fOut.write(fIn.read(UINT16_LENGTH * 3)) # rest
    fOut.write(fIn.read(startOffset + chunkInfo["commonHeader"]["headerSize"] + attrStart - fIn.tell())) # in case there is anything here
    for _ in range(currAttrCount):
        patchAttribute(fIn, fOut, debuggableStringId)
    fOut.write(fIn.read(end - fIn.tell())) # incase there is anything here

def patchAttribute(fIn, fOut, debuggableStringId):
    patchStringRef(fIn, fOut, debuggableStringId) # ns
    patchStringRef(fIn, fOut, debuggableStringId) # name
    patchStringRef(fIn, fOut, debuggableStringId) # rawValue
    (size, res0, type) = unpack("<HBB", fIn.read(4))
    fOut.write(pack("<HBB", size, res0, type))
    if type == 0x03: # string
        patchStringRef(fIn, fOut, debuggableStringId)
    else:
        fOut.write(fIn.read(UINT32_LENGTH)) # data

def patchChunk(f, chunkInfo, fOut, debuggableStringId):
    f.seek(chunkInfo["startOffset"])
    fOut.write(f.read(COMMON_HEADER_LEN)) # copy header
    type = chunkInfo["commonHeader"]["type"]
    if type >= 0x0100 and type <= 0x17f:
        patchNode(f, fOut, debuggableStringId)
        if type == 0x100 or type == 0x101: # start/end NS
            patchNamespaceExt(f, fOut, debuggableStringId)
        elif type == 0x102: # start
            patchAttrExt(f, fOut, chunkInfo, debuggableStringId)
        elif type == 0x103: # end element
            patchEndElementExt(f, fOut, debuggableStringId)
        elif type == 0x104: # cdata
            patchCDataExt(f, fOut, debuggableStringId)
        else:
            fOut.write(f.read(chunkInfo["commonHeader"]["chunkSize"] - chunkInfo["commonHeader"]["headerSize"]))
    else:
        fOut.write(f.read(chunkInfo["commonHeader"]["chunkSize"] - COMMON_HEADER_LEN)) # already copied common header

# attrs are sorted by ref id!
def patchApplicationAttributes(fIn, fOut, attrCount, resmapInfo, debuggableStringId, androidNsId):
    inserted = False
    for i in range(attrCount):
        # first get name
        fIn.seek(UINT32_LENGTH, SEEK_CUR) # skip ns
        name = readInt(fIn, 1) # read nameId
        if readResId(fIn, resmapInfo, name) > DEBUGGABLE_RES_ID and not inserted:
            # first with resId >, insert here:
            fOut.write(pack("<5L", androidNsId, debuggableStringId, 0xFFFFFFFF, 0x12000008, 0xFFFFFFFF))
            inserted = True
        fIn.seek(-2 * UINT32_LENGTH, SEEK_CUR) # roll back to start of attribute
        patchAttribute(fIn, fOut, debuggableStringId)
    if not inserted: # all attribute res ids were < debuggable res id
        fOut.write(pack("<5L", androidNsId, debuggableStringId, 0xFFFFFFFF, 0x12000008, 0xFFFFFFFF))

def patchApplicationElement(fIn, chunkInfo, androidNsId, debuggableStringId, fOut, resmapInfo):
    startOffset = chunkInfo["startOffset"]
    headerSize = chunkInfo["commonHeader"]["headerSize"]
    fIn.seek(startOffset + COMMON_HEADER_LEN) # we create a new common header
    newChunkSize = chunkInfo["commonHeader"]["chunkSize"] + ATTRIBUTE_LENGTH # new attribute length
    writeCommonHeader(fOut, chunkInfo["commonHeader"]["type"], headerSize, newChunkSize)
    patchNode(fIn, fOut, debuggableStringId) # lineNo and comment
    patchStringRef(fIn, fOut, debuggableStringId) # ns
    patchStringRef(fIn, fOut, debuggableStringId) # name
    (attrStart, attrSize, currAttrCount) = readShort(fIn, 3)
    fOut.write(pack("<HHH", attrStart, attrSize, currAttrCount + 1))
    fOut.write(fIn.read(UINT16_LENGTH * 3)) # copy id, class and style
    fOut.write(fIn.read(startOffset + headerSize + attrStart - fIn.tell())) # in case there is anything here
    # now patch attributes
    patchApplicationAttributes(fIn, fOut, currAttrCount, resmapInfo, debuggableStringId, androidNsId)
    fOut.write(fIn.read(startOffset + chunkInfo["commonHeader"]["chunkSize"] - fIn.tell())) # incase there is anything here

def findAndroidNsIdx(fIn, strPoolInfo):
    pos = fIn.tell()
    for i in range(strPoolInfo["stringCount"]):
        if readString(fIn, strPoolInfo, i) == ANDROID_NS_STRING:
            fIn.seek(pos)
            return i
    raise Exception("No android ns found ...")

# in order for the application to be counted as debuggable the application
# tag needs to contain an attribute whose resource id is debuggable res id
# thus, the name value must be X with resmap[x] = deuggable res id and strings[x] = "debuggable"
# within the application tag, attributes must be sorted by res id

# find application tag
# find attribute with name == "debuggable"(DEBUGGABLE_RES_IDX)
# if exists: set to true -> done
# else:
#   create new attribute with name = len(resmap)
#   add resmap entry
#   insert "debuggable" string entry at len(resmap)

# rebuild file
#   if only attr value changed:
#       copy file but write 0xFFFFFFFF at correct offset instead of 0x00000000
#   otherwise:
#   add N to filesize header
#   update string pool , res map and all attribute name values ...
def patchManifest(fIn, fOut):
    fileHeader = readCommonHeader(fIn)
    if fileHeader["headerSize"] != COMMON_HEADER_LEN:
        raise Exception("File header not of size 8!")
    chunks = readChunks(fIn)
    (stringPoolIdx, resmapIdx) = findStringpoolAndResmap(chunks)
    strPoolInfo = decodeStringPoolInfo(fIn, chunks[stringPoolIdx])
    if resmapIdx == -1:
        resmapInfo = {
            "chunkInfo": None,
            "len": 0,
        }
    if resmapIdx >= 0:
        resMapLen = calculateResMapLength(chunks[resmapIdx])
        resmapInfo = {
            "chunkInfo": chunks[resmapIdx],
            "len": resMapLen
        }
    applicationIdx = findApplication(fIn, chunks, strPoolInfo)
    print("Found application tag at {} !".format(chunks[applicationIdx]["startOffset"]))
    applicationAttributes = decodeAttributes(fIn, chunks[applicationIdx])
    debuggableAttributeIdx = findDebuggableAttribute(fIn, strPoolInfo, resmapInfo, applicationAttributes)
    if debuggableAttributeIdx >= 0:
        print("Found debuggable attribute!")
        debuggableValueAbsoluteOffset = applicationAttributes[debuggableAttributeIdx]["startOffset"] + 16 # offset of data word
        print("Copying file ...")
        fIn.seek(0)
        fOut.write(fIn.read(debuggableValueAbsoluteOffset))
        fOut.write(DEBUGGABLE_VALUE_TRUE)
        fIn.seek(4, SEEK_CUR)
        fOut.write(fIn.read())
        return
    else:
        print("Debuggable not present, need to update string pool, res map and attributes ...")
        # write new file header
        totalSizeIncrement = DEBUGGABLE_STRING_LENGTH_UTF8 if strPoolInfo["isUtf8"] else DEBUGGABLE_STRING_LENGTH_UTF16 # new string
        totalSizeIncrement += UINT32_LENGTH # new string offset
        totalSizeIncrement += UINT32_LENGTH # resmap entry
        if resmapIdx == -1:
            totalSizeIncrement += COMMON_HEADER_LEN # new resmap chunk requires +8 for header
        totalSizeIncrement += ATTRIBUTE_LENGTH # new attribute
        writeCommonHeader(fOut, fileHeader["type"], fileHeader["headerSize"], fileHeader["chunkSize"] + totalSizeIncrement)
        # get android ns string id
        androidNsId = findAndroidNsIdx(fIn, strPoolInfo)
        debuggableStringId = resmapInfo["len"] # every ref >= must be incremented ...
        if androidNsId >= debuggableStringId:
            androidNsId += 1
        print("Injecting 'debuggable' at index {} ...".format(debuggableStringId))
        i = 0
        chunkLen = len(chunks)
        while i < chunkLen:
            chunkInfo = chunks[i]
            if i == stringPoolIdx + 1 and resmapIdx < 0: # inject new resmap
                injectResmap(fOut)
                i -= 1 # dont inrease i
            elif i == stringPoolIdx:
                patchStringPool(fIn, strPoolInfo, fOut, debuggableStringId)
            elif i == resmapIdx:
                patchResmap(fIn, resmapInfo, fOut)
            elif i == applicationIdx:
                patchApplicationElement(fIn, chunkInfo, androidNsId, debuggableStringId, fOut, resmapInfo)
            else:
                patchChunk(fIn, chunkInfo, fOut, debuggableStringId)
            i += 1

def patchManifestByFilename(fnIn, fnOut):
    with BytesIO() as tmp:
        with open(fnIn, "rb") as fIn:
            patchManifest(fIn, tmp)
        tmp.seek(0)
        with open(fnOut, "wb") as fOut:
            fOut.write(tmp.read())

def extractToDir(zfn, dir):
    with ZipFile(zfn, "r") as zf:
        zf.extractall(dir)

def patchApk(fnIn, fnOut, keystore, keyAlias, keystorePass):
    inZip = ZipFile(fnIn, "r")
    outZip = ZipFile(fnOut + ".tmp", "w")

    print("Patching AndroidManifest.xml ...")
    androidManifestPath = "AndroidManifest.xml"
    with BytesIO() as tmp:
        with inZip.open(androidManifestPath, "r") as fIn:
            patchManifest(fIn, tmp)
        tmp.seek(0)
        with outZip.open(androidManifestPath, "w") as fOut:
            fOut.write(tmp.read())

    print("Copying rest of files")
    for file in inZip.infolist():
        if file.filename in [androidManifestPath]:
            continue
        with inZip.open(file, "r") as fIn:
            with outZip.open(file, "w") as fOut:
                while chunk := fIn.read(8192):
                    fOut.write(chunk)

    inZip.close()
    outZip.close()

    zipAlignLoc = which("zipalign")
    if not zipAlignLoc:
        print("zipalign not found in path, aborting.")
        sys.exit(1)
    print("Using zipalign at " + zipAlignLoc)

    print("Aligning...")
    if subprocess.run([zipAlignLoc, "-p", "-v", "4", outZip.filename, fnOut]).returncode != 0:
        print("zipalign failed, aborting.")
        sys.exit(1)

    print("Verifying alignment...")
    if subprocess.run([zipAlignLoc, "-c", "-v", "4", fnOut]).returncode != 0:
        print("Alignment verification failed, aborting.")
        sys.exit(1)

    apksignerLoc = which("apksigner")
    if not apksignerLoc:
        print("apksigner not found in path, aborting.")
        sys.exit(1)
    print("Using apksigner at " + apksignerLoc)

    print("Signing...")
    if subprocess.run([apksignerLoc, "sign", "--ks", keystore, "--ks-key-alias", keyAlias, "--ks-pass", f"pass:{keystorePass}", fnOut]).returncode != 0:
        print("apksigner failed, aborting.")
        sys.exit(1)

    print("Verifying signature...")
    if subprocess.run([apksignerLoc, "verify", fnOut]).returncode != 0:
        print("Signature verification failed, aborting.")
        sys.exit(1)

    print("Removing temporary file...")
    os.remove(outZip.filename)


if __name__ == "__main__":
    option = sys.argv[1]
    if option == "xml":
        if len(sys.argv) == 3:
            with open(sys.argv[2], "rb") as fIn:
                with BytesIO() as fOut:
                    patchManifest(fIn, fOut)
        else:
            patchManifestByFilename(sys.argv[2], sys.argv[3])
    elif option == "apk":
        patchApk(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    else:
        print("Usage: apk [fileIn] [fileOut] [keystore] [key alias] [keystore password] or xml [fileIn] [fileOut]")
