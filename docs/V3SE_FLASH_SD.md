# V3 SE stock mainboard firmware: manual SD-card flashing

**Initial build asset is pending. Do not flash until its exact accepted `.config` has been captured and verified.**

The physically accepted target was STM32F103xe, 28 KiB bootloader, USART1 serial on PA10/PA9, plus the stock display USART2 PA2/PA3 bridge. Use the accepted build configuration byte-for-byte rather than reconstructing menuconfig answers from this description.

The first clean-install build uses pinned source `ab759b0026ca69396446bf13b7a9767c59619297` and verifies exact `.config` SHA256 `ee38872bc64d4595af07445078013b5e366b796d360781b07c99c60a574e7777` before making `out/klipper.bin`.

On a clean, separate runtime source checkout, build using `install/build-firmware.sh --check SOURCE_DIR`, then `--build SOURCE_DIR`. Never point this at the accepted live development host or a source tree containing an existing `.config`.

Manually copy the resulting `out/klipper.bin` onto a suitable SD card as a uniquely named `.BIN` file. The V3 SE bootloader requires a different filename from the one most recently flashed. The accepted reference used `KL4A59.BIN`, **not** an instruction to reuse that name. Confirm the SD copy's checksum, power the printer off, insert the SD, flash with a mainboard power cycle, and verify the connected MCU identity. Do not claim success on a failed identity check.

The historical accepted binary SHA256 `d9269370423b9be83e4fa4a38e9fa09638de9dbdb9142714b378a625b526ccd9` is reference evidence, not a requirement that a newly built binary have identical bytes across different toolchains.
