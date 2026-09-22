local mod = get_mod("RainbowFlame")

return {
    name = mod:localize("mod_name"),
    description = mod:localize("mod_description"),
    is_togglable = true,
    options = {
        widgets = {
            {
                setting_id = "soulblaze_group",
                type = "group",
                sub_widgets = {
                    {
                        setting_id = "enemy_color",
                        type = "dropdown",
                        default_value = "original",
                        options = {
                            { text = "enemy_color_original", value = "original" },
                            { text = "enemy_color_red", value = "red" },
                            { text = "enemy_color_orange", value = "orange" },
                            { text = "enemy_color_yellow", value = "yellow" },
                            { text = "enemy_color_green", value = "green" },
                            { text = "enemy_color_cyan", value = "cyan" },
                            { text = "enemy_color_blue", value = "blue" },
                            { text = "enemy_color_violet", value = "violet" },
                            { text = "enemy_color_pink", value = "pink" },
                        },
                    },
                    {
                        setting_id = "enemy_opacity",
                        type = "dropdown",
                        default_value = 100,
                        options = {
                            { text = "enemy_opacity_0", value = 0 },
                            { text = "enemy_opacity_25", value = 25 },
                            { text = "enemy_opacity_50", value = 50 },
                            { text = "enemy_opacity_75", value = 75 },
                            { text = "enemy_opacity_100", value = 100 },
                        },
                    },
                },
            },
            {
                setting_id = "flame_group",
                type = "group",
                sub_widgets = {
                    {
                        setting_id = "original_color", type = "checkbox", default_value = false,
                    },
                    { setting_id = "hue", type = "numeric", default_value = 120, range = { 0, 360 }, decimals_number = 0 },
                    { setting_id = "brightness", type = "numeric", default_value = 1, range = { 0, 2 }, decimals_number = 2 },
                    { setting_id = "opacity", type = "numeric", default_value = 1, range = { 0, 1 }, decimals_number = 2 },
                },
            },
            {
                setting_id = "rainbow_group",
                type = "group",
                sub_widgets = {
                    { setting_id = "rainbow", type = "checkbox", default_value = false },
                    { setting_id = "speed", type = "numeric", default_value = 0.125, range = { 0.001, 4 }, decimals_number = 3 },
                },
            },
            {
                setting_id = "flamer_flame_group",
                type = "group",
                sub_widgets = {
                    { setting_id = "flamer_original_color", type = "checkbox", default_value = true },
                    { setting_id = "flamer_hue", type = "numeric", default_value = 30, range = { 0, 360 }, decimals_number = 0 },
                    { setting_id = "flamer_brightness", type = "numeric", default_value = 1, range = { 0, 2 }, decimals_number = 2 },
                    { setting_id = "flamer_opacity", type = "numeric", default_value = 1, range = { 0, 1 }, decimals_number = 2 },
                },
            },
            {
                setting_id = "flamer_rainbow_group",
                type = "group",
                sub_widgets = {
                    { setting_id = "flamer_rainbow", type = "checkbox", default_value = false },
                    { setting_id = "flamer_speed", type = "numeric", default_value = 0.125, range = { 0.001, 4 }, decimals_number = 3 },
                },
            },
        },
    },
}
