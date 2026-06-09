#!/usr/bin/env bash
# Build GRUB 2.12 without stack protector for Kouprey Boot
# Run this on Debian/Ubuntu with: bash build-grub.sh
#
# Requirements:
#   apt install -y build-essential git bison flex gettext texinfo autoconf automake
#   apt install -y gcc-mingw-w64-x86-64 gcc-mingw-w64-i686

set -euo pipefail

GRUB_VERSION="grub-2.12"
SRC_DIR="/tmp/${GRUB_VERSION}"
OUTPUT_DIR="$(dirname "$(readlink -f "$0")")/assets/boot"

echo "=== Downloading GRUB 2.12 ==="
if [ ! -f "/tmp/${GRUB_VERSION}.tar.xz" ]; then
    wget -O "/tmp/${GRUB_VERSION}.tar.xz" \
        "https://ftp.gnu.org/gnu/grub/${GRUB_VERSION}.tar.xz"
fi

echo "=== Extracting ==="
rm -rf "$SRC_DIR"
cd /tmp
tar xf "${GRUB_VERSION}.tar.xz"
cd "$SRC_DIR"

echo "=== Building x86_64-efi (without stack protector) ==="
mkdir -p build-x86_64 && cd build-x86_64
../configure \
    --target=x86_64-w64-mingw32 \
    --with-platform=efi \
    --host=x86_64-w64-mingw32 \
    --disable-stack-protector \
    --enable-efi \
    --prefix=/tmp/grub-install-x86_64
make -j"$(nproc)"
make install
cd ..

echo "=== Building i386-efi (without stack protector) ==="
mkdir -p build-i386 && cd build-i386
../configure \
    --target=i686-w64-mingw32 \
    --with-platform=efi \
    --host=i686-w64-mingw32 \
    --disable-stack-protector \
    --enable-efi \
    --prefix=/tmp/grub-install-i386
make -j"$(nproc)"
make install
cd ..

echo "=== Installing binaries to Kouprey Boot assets ==="
# Copy EFI binary
mkdir -p "${OUTPUT_DIR}/EFI/BOOT"
cp /tmp/grub-install-x86_64/lib/grub/x86_64-efi/grub.efi \
    "${OUTPUT_DIR}/EFI/BOOT/BOOTX64.EFI"
cp /tmp/grub-install-x86_64/lib/grub/x86_64-efi/grub.efi \
    "${OUTPUT_DIR}/EFI/BOOT/grubx64_real.efi"

# Copy modules
rm -rf "${OUTPUT_DIR}/grub/x86_64-efi"
cp -r /tmp/grub-install-x86_64/lib/grub/x86_64-efi \
    "${OUTPUT_DIR}/grub/x86_64-efi"

rm -rf "${OUTPUT_DIR}/grub/i386-efi"
cp -r /tmp/grub-install-i386/lib/grub/i386-efi \
    "${OUTPUT_DIR}/grub/i386-efi"

# Clean up modinfo.sh (remove path references to /tmp)
for f in "${OUTPUT_DIR}/grub/x86_64-efi/modinfo.sh" \
         "${OUTPUT_DIR}/grub/i386-efi/modinfo.sh"; do
    if [ -f "$f" ]; then
        sed -i 's|/tmp/grub-[^/]*|.|g' "$f" 2>/dev/null || true
    fi
done

echo ""
echo "=== Done! ==="
echo "GRUB EFI binaries rebuilt without stack protector."
echo "Verify: grep 'stack_protector' ${OUTPUT_DIR}/grub/x86_64-efi/modinfo.sh"
