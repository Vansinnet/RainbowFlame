local mod = get_mod("RainbowFlame")

return {
    name = mod:localize("mod_name"),
    description = mod:localize("mod_description"),
    is_togglable = true,
    options = {
        widgets = {
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
                setting_id = "original_color", type = "checkbox", default_value = false,
            },
            { setting_id = "hue", type = "numeric", default_value = 120, range = { 0, 360 }, decimals_number = 0 },
            { setting_id = "brightness", type = "numeric", default_value = 1, range = { 0, 2 }, decimals_number = 2 },
            { setting_id = "rainbow", type = "checkbox", default_value = false },
            { setting_id = "speed", type = "numeric", default_value = 0.125, range = { 0.001, 4 }, decimals_number = 3 },
        },
    },
}
