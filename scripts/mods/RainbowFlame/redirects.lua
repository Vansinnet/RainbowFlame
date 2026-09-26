local mod = get_mod("RainbowFlame")
local redirect = mod:io_dofile("RainbowFlame/scripts/mods/RainbowFlame/asset_redirect")
local files = mod:io_dofile("RainbowFlame/scripts/mods/RainbowFlame/redirect_files")

if not redirect or not files then
    mod:error("RainbowFlame could not load Asset Redirect; stock effects will be used.")
    return nil
end

local handles = {}
for i = 1, #files do
    handles[i] = redirect.register(mod, files[i])
end

return {
    commit = function()
        redirect.commit()
        local served = 0
        local restart = false
        for i = 1, #handles do
            local status = redirect.state(handles[i])
            if status == "active" or status == "shared" then
                served = served + 1
            elseif status == "restart_required" then
                restart = true
            end
        end
        mod:info("resource redirects served: %d of %d", served, #handles)
        if served ~= #handles then
            mod:echo("RainbowFlame: resource redirects incomplete (%d/%d); stock effects remain active. Check the log.", served, #handles)
        end
        if restart then
            mod:echo("RainbowFlame: restart Darktide to apply resource redirects.")
        end
        return served == #handles
    end,
    clear = function()
        redirect.clear(mod)
    end,
}
