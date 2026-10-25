#pragma once

enum boot_choice { BOOT_IOS, BOOT_MIUI, BOOT_OFF };

/* The boot menu; have_miui: whether the image carries an Android kernel to pick. */
enum boot_choice boot_menu(int have_miui);
