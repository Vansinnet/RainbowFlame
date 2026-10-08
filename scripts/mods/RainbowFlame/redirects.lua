local mod = get_mod("RainbowFlame")
local reforge = mod:io_dofile("RainbowFlame/scripts/mods/RainbowFlame/reforge")

if not reforge then
    mod:error("RainbowFlame could not load Reforge; stock effects will be used.")
    return nil
end

-- Edit reforge.json and run `reforge build` to change the replaced files.
--
-- Darktide reads its weapon effect bundles before any mod runs, so a
-- replacement for those must fit the stock size. The colour presets that
-- RainbowFlame adds (impact and enemy Soulblaze variants) therefore live in
-- the unused debug package below, which the game never loads on its own.
-- RainbowFlame loads it after Reforge is serving the files.
-- The presets use textures from the stock Soulblaze and impact packages, which
-- must be loaded first or they bind to the engine's default texture (impacts
-- then render as flat colour squares). The impact packages are otherwise only
-- loaded with the weapon, usually after this runs.
local PRESET_PACKAGES = {
    "content/fx/particles/enemies/buff_warpfire",
    "content/fx/particles/weapons/flame_staff/psyker_flame_staff_impact_delay",
    "content/fx/particles/weapons/rifles/zealot_flamer/zealot_flamer_impact_delay",
    "content/fx/particles/debug/flame_thrower_test",
}
local manifest = "RainbowFlame/scripts/mods/RainbowFlame/reforge_manifest"
local handles = reforge.register_manifest(mod, manifest)

local function load_presets()
    for i = 1, #PRESET_PACKAGES do
        local package = PRESET_PACKAGES[i]
        local status = mod.package_status and mod:package_status(package)
        if status ~= "loaded" and status ~= "queued" then
            local ok, err = pcall(mod.load_package, mod, package, nil, true)
            if not ok then
                mod:info("colour presets unavailable (%s): %s", package, tostring(err))
                return
            end
        end
    end
end

return {
    commit = function()
        reforge.commit()
        local served = 0
        local restart = false
        local displaced_by = nil
        for i = 1, #handles do
            local handle = handles[i]
            local state = reforge.state(handle)
            if reforge.served(state) then
                served = served + 1
            elseif state == "restart_required" then
                restart = true
            else
                if state == "displaced" then
                    displaced_by = displaced_by or reforge.winner(handle)
                end
                mod:info("resource %s not served: %s %s", handle.stock, state, reforge.reason(handle) or "")
            end
        end
        mod:info("resource redirects served: %d of %d", served, #handles)
        if restart then
            mod:echo("RainbowFlame: restart Darktide to apply resource redirects.")
        elseif displaced_by then
            -- Withdraw every file so the other mod runs against stock files
            -- instead of a mix of both mods' resources.
            reforge.clear(mod)
            mod:echo("RainbowFlame: %s replaces the same flame resources, so RainbowFlame's effects stay off. Use one of the two mods.", displaced_by)
        elseif #handles == 0 or served ~= #handles then
            mod:echo("RainbowFlame: resource redirects incomplete (%d/%d); stock effects remain active. Check the log or /reforge.", served, #handles)
        end
        local ready = #handles > 0 and served == #handles
        if ready then
            load_presets()
        end
        return ready
    end,
    clear = function()
        reforge.clear(mod)
    end,
}
