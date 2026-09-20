return {
    run = function()
        fassert(rawget(_G, "new_mod"), "`RainbowFlame` failed loading DMF.")
        new_mod("RainbowFlame", {
            mod_script = "RainbowFlame/scripts/mods/RainbowFlame/RainbowFlame",
            mod_data = "RainbowFlame/scripts/mods/RainbowFlame/RainbowFlame_data",
            mod_localization = "RainbowFlame/scripts/mods/RainbowFlame/RainbowFlame_localization",
        })
    end,
    packages = {},
}
