local mod = {}
local hooks = {}
local registered = {}
local refused
local cleared
local native = {
    register = function(_, entry)
        registered[#registered + 1] = entry
        return #registered
    end,
    commit = function() end,
    state = function(handle)
        return handle == refused and "refused" or "active"
    end,
    clear = function() cleared = true end,
}
local env = setmetatable({}, { __index = _G })
env._G = env
env.get_mod = function() return mod end
env.World = {}
env.DEDICATED_SERVER = false
env.QuaternionBox = function()
    return { unbox = function() return nil end }
end
env.Vector3Box = env.QuaternionBox

function mod:io_dofile(path)
    if path:match("/asset_redirect$") then
        return native
    end
    return assert(loadfile("scripts/mods/RainbowFlame/" .. path:match("([^/]+)$") .. ".lua", "t", env))()
end
function mod:hook(object, name, fn)
    if object == "World" and name == "create_particles" then hooks.create_particles = fn end
end
function mod:hook_safe() end
function mod:is_enabled() return true end
function mod:info() end
function mod:echo() end
function mod:get(name)
    local values = {
        rainbow = false, original_color = false, hue = 120, opacity = 1,
        brightness = 1, speed = 1, flamer_rainbow = false,
        flamer_original_color = false, flamer_hue = 120, flamer_opacity = 1,
        flamer_brightness = 1, flamer_speed = 1, enemy_color = "red",
        enemy_opacity = 100,
    }
    return values[name]
end

assert(loadfile("scripts/mods/RainbowFlame/RainbowFlame.lua", "t", env))()
assert(#registered == 168)
local original = "content/fx/particles/enemies/buff_warpfire"
local function create(effect)
    return hooks.create_particles(function(_, name) return name end, {}, effect)
end

mod.on_enabled()
refused = 1
mod.on_all_mods_loaded()
assert(create(original) == original, "Refused bundle must not swap the particle effect")
refused = nil
mod.on_all_mods_loaded()
assert(create(original) == "content/fx/particles/rainbow_flame/buff_warpfire_red")
mod.on_disabled()
assert(create(original) == original, "Disabled mod must not swap the particle effect")
mod.on_unload()
assert(cleared)
print("168 redirect registrations and stock fallback/disable cleanup passed")
