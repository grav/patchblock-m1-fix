// usbreplug - force re-enumeration of the Patchblock LPC1343 USB bootloader
// (the software equivalent of unplugging and replugging the cable).
// Build: clang -o usbreplug usbreplug.c -framework IOKit -framework CoreFoundation
#include <stdio.h>
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/usb/IOUSBLib.h>
#include <IOKit/IOCFPlugIn.h>

int main(void) {
    int vid = 0x04CC, pid = 0x0003;            // NXP LPC13XX IFLASH (USB ISP)
    CFMutableDictionaryRef match = IOServiceMatching("IOUSBHostDevice");
    CFNumberRef v = CFNumberCreate(NULL, kCFNumberIntType, &vid);
    CFNumberRef p = CFNumberCreate(NULL, kCFNumberIntType, &pid);
    CFDictionarySetValue(match, CFSTR("idVendor"), v);
    CFDictionarySetValue(match, CFSTR("idProduct"), p);
    io_service_t dev = IOServiceGetMatchingService(kIOMainPortDefault, match);
    if (!dev) { fprintf(stderr, "bootloader not found on USB bus\n"); return 2; }

    IOCFPlugInInterface **plug = NULL; SInt32 score;
    if (IOCreatePlugInInterfaceForService(dev, kIOUSBDeviceUserClientTypeID,
            kIOCFPlugInInterfaceID, &plug, &score) != KERN_SUCCESS || !plug) {
        fprintf(stderr, "plugin interface failed\n"); return 1;
    }
    IOUSBDeviceInterface **usb = NULL;
    (*plug)->QueryInterface(plug, CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID), (LPVOID *)&usb);
    IODestroyPlugInInterface(plug);
    if (!usb) { fprintf(stderr, "device interface failed\n"); return 1; }

    kern_return_t kr = (*usb)->USBDeviceOpen(usb);
    if (kr) fprintf(stderr, "open: 0x%x (continuing; may need sudo)\n", kr);
    kr = (*usb)->USBDeviceReEnumerate(usb, 0);
    if (kr) { fprintf(stderr, "re-enumerate failed: 0x%x\n", kr); return 1; }
    printf("re-enumeration requested - device should reappear in a few seconds\n");
    (*usb)->USBDeviceClose(usb);
    (*usb)->Release(usb);
    return 0;
}
