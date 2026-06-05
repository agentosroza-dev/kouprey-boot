# Fix boot_iso initrd logic bug

## Problem

In `worker.py:108-156`, the `linux` command is placed INSIDE each initrd `if`
block. If the kernel file exists (e.g. `casper/vmlinuz`) but none of the 4
initrd variants (`initrd.lz`, `initrd`, `initrd.img`, `initrd.gz`) match,
the `linux` command never executes and the function silently drops through
without booting. The "Unknown ISO type" error at line 154 is also unreachable
because the outer `if` already matched.

## Fix

Move `linux` outside the initrd checks so it always runs when the kernel
exists, then pick whichever initrd variant is available.

## Exact edit

### Before (lines 110-137):
```python
  if [ -f (loop)/casper/vmlinuz ]; then
    if [ -f (loop)/casper/initrd.lz ]; then
      linux (loop)/casper/vmlinuz boot=casper iso-scan/filename="$1" quiet splash ---
      initrd (loop)/casper/initrd.lz
    elif [ -f (loop)/casper/initrd ]; then
      linux (loop)/casper/vmlinuz boot=casper iso-scan/filename="$1" quiet splash ---
      initrd (loop)/casper/initrd
    elif [ -f (loop)/casper/initrd.img ]; then
      linux (loop)/casper/vmlinuz boot=casper iso-scan/filename="$1" quiet splash ---
      initrd (loop)/casper/initrd.img
    elif [ -f (loop)/casper/initrd.gz ]; then
      linux (loop)/casper/vmlinuz boot=casper iso-scan/filename="$1" quiet splash ---
      initrd (loop)/casper/initrd.gz
    fi
  elif [ -f (loop)/casper/vmlinuz.efi ]; then
    if [ -f (loop)/casper/initrd.lz ]; then
      linux (loop)/casper/vmlinuz.efi boot=casper iso-scan/filename="$1" quiet splash ---
      initrd (loop)/casper/initrd.lz
    elif [ -f (loop)/casper/initrd ]; then
      linux (loop)/casper/vmlinuz.efi boot=casper iso-scan/filename="$1" quiet splash ---
      initrd (loop)/casper/initrd
    elif [ -f (loop)/casper/initrd.img ]; then
      linux (loop)/casper/vmlinuz.efi boot=casper iso-scan/filename="$1" quiet splash ---
      initrd (loop)/casper/initrd.img
    elif [ -f (loop)/casper/initrd.gz ]; then
      linux (loop)/casper/vmlinuz.efi boot=casper iso-scan/filename="$1" quiet splash ---
      initrd (loop)/casper/initrd.gz
    fi
```

### After (lines 110-137):
```python
  if [ -f (loop)/casper/vmlinuz ]; then
    linux (loop)/casper/vmlinuz boot=casper iso-scan/filename="$1" quiet splash ---
    if [ -f (loop)/casper/initrd.lz ]; then
      initrd (loop)/casper/initrd.lz
    elif [ -f (loop)/casper/initrd ]; then
      initrd (loop)/casper/initrd
    elif [ -f (loop)/casper/initrd.img ]; then
      initrd (loop)/casper/initrd.img
    elif [ -f (loop)/casper/initrd.gz ]; then
      initrd (loop)/casper/initrd.gz
    fi
  elif [ -f (loop)/casper/vmlinuz.efi ]; then
    linux (loop)/casper/vmlinuz.efi boot=casper iso-scan/filename="$1" quiet splash ---
    if [ -f (loop)/casper/initrd.lz ]; then
      initrd (loop)/casper/initrd.lz
    elif [ -f (loop)/casper/initrd ]; then
      initrd (loop)/casper/initrd
    elif [ -f (loop)/casper/initrd.img ]; then
      initrd (loop)/casper/initrd.img
    elif [ -f (loop)/casper/initrd.gz ]; then
      initrd (loop)/casper/initrd.gz
    fi
```

**File**: `C:\Users\Agentos\Desktop\kouprey-boot\worker.py`
**Lines**: 110-137 (replace old block with new block above)
