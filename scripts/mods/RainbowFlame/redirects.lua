local mod = get_mod("RainbowFlame")
local reforge = mod:io_dofile("RainbowFlame/scripts/mods/RainbowFlame/reforge")

if not reforge then
    mod:error("RainbowFlame could not load Reforge; stock effects will be used.")
    return nil
end

-- 16 stock resources are replaced (pinned by SHA-256) and 152 material
-- streams are served at new bundle/data/rf/ paths. Edit reforge.json and run
-- `reforge build` to change this list.
local manifest = "RainbowFlame/scripts/mods/RainbowFlame/reforge_manifest"
local handles = reforge.register_manifest(mod, manifest)

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
        return #handles > 0 and served == #handles
    end,
    clear = function()
        reforge.clear(mod)
    end,
}
