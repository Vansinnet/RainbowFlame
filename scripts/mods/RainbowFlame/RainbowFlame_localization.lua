return {
    mod_name = { en = "RainbowFlame" },
    mod_description = {
        en = "Customize the Inferno staff and its wall impact, and choose a fixed color preset for persistent enemy Soulblaze.",
    },
    soulblaze_group = { en = "Soulblaze" },
    flame_group = { en = "Flame" },
    rainbow_group = { en = "Rainbow" },
    enemy_color = { en = "Enemy Soulblaze color" },
    enemy_color_description = {
        en = "Selects the color of new persistent Soulblaze flames on enemies. Existing burns keep their current appearance, so apply Soulblaze again after changing this option. Original uses the game's normal color. This does not affect the staff.",
    },
    enemy_color_original = { en = "Original" },
    enemy_color_red = { en = "Red" },
    enemy_color_orange = { en = "Orange" },
    enemy_color_yellow = { en = "Yellow" },
    enemy_color_green = { en = "Green" },
    enemy_color_cyan = { en = "Cyan" },
    enemy_color_blue = { en = "Blue" },
    enemy_color_violet = { en = "Violet" },
    enemy_color_pink = { en = "Pink" },
    enemy_opacity = { en = "Enemy Soulblaze opacity" },
    enemy_opacity_description = {
        en = "Selects the visibility of new persistent Soulblaze flames on enemies. Existing burns keep their current appearance. This does not affect the staff or wall impacts.",
    },
    enemy_opacity_0 = { en = "0%%" },
    enemy_opacity_25 = { en = "25%%" },
    enemy_opacity_50 = { en = "50%%" },
    enemy_opacity_75 = { en = "75%%" },
    enemy_opacity_100 = { en = "100%%" },
    original_color = { en = "Original color" },
    original_color_description = {
        en = "Uses the Inferno staff's original multi-color flame and wall impact. This overrides Color, and the original appearance ignores Brightness. Rainbow takes priority while enabled. This does not affect enemy Soulblaze.",
    },
    rainbow = { en = "Rainbow" },
    rainbow_description = {
        en = "Cycles the staff flame through the full color wheel and its original multi-color appearance. The wall impact remains original in this mode. Rainbow overrides Original color and Color while enabled. Enemy Soulblaze presets are separate.",
    },
    hue = { en = "Color" },
    hue_description = {
        en = "Selects the staff flame hue when Original color and Rainbow are both off. The wall impact uses the nearest red, orange, yellow, green, cyan, blue, violet, or pink preset. This does not affect enemy Soulblaze.",
    },
    brightness = { en = "Brightness" },
    brightness_description = {
        en = "Adjusts brightness for the staff's custom Color and Rainbow modes. Wall impacts, Original color, and enemy Soulblaze presets ignore this option.",
    },
    opacity = { en = "Opacity" },
    opacity_description = {
        en = "Adjusts the visibility of the staff flame in Original color, custom Color, and Rainbow modes. 0 is invisible and 1 is fully visible. Wall impacts and enemy Soulblaze presets ignore this option.",
    },
    speed = { en = "Speed" },
    speed_description = {
        en = "Controls how quickly the staff's Rainbow mode changes color. 0.125 is the default and higher values cycle faster. This option has no effect while Rainbow is off and does not affect wall impacts or enemy Soulblaze.",
    },
}
