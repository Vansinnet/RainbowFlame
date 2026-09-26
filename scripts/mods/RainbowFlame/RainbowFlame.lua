---@class RainbowFlameMod : DMFMod
local mod = get_mod("RainbowFlame")
local redirects = mod:io_dofile("RainbowFlame/scripts/mods/RainbowFlame/redirects")

local clouds = {
    "RainbowFlame_stream_a",
    "RainbowFlame_stream_b",
    "RainbowFlame_stream_c",
}
local husk_clouds = {
    "RainbowFlame_stream_a",
    "RainbowFlame_stream_3p_b",
    "RainbowFlame_stream_3p_c",
    "RainbowFlame_stream_3p_d",
}
local flamer_profiles = {
    {
        clouds = {
            "RainbowFlame_flamer_continuous_a",
            "RainbowFlame_flamer_continuous_b",
            "RainbowFlame_flamer_continuous_c",
            "RainbowFlame_flamer_continuous_d",
        },
    },
    {
        clouds = {
            "RainbowFlame_flamer_burst_a",
            "RainbowFlame_flamer_burst_b",
            "RainbowFlame_flamer_burst_c",
            "RainbowFlame_flamer_burst_d",
            "RainbowFlame_flamer_burst_e",
        },
    },
    {
        clouds = {
            "RainbowFlame_flamer_3p_a",
            "RainbowFlame_flamer_3p_b",
            "RainbowFlame_flamer_3p_c",
        },
    },
}
local enemy_effect = "content/fx/particles/enemies/buff_warpfire"
local enemy_presets = {
    red = "content/fx/particles/rainbow_flame/buff_warpfire_red",
    orange = "content/fx/particles/rainbow_flame/buff_warpfire_orange",
    yellow = "content/fx/particles/rainbow_flame/buff_warpfire_yellow",
    green = "content/fx/particles/rainbow_flame/buff_warpfire_green",
    cyan = "content/fx/particles/rainbow_flame/buff_warpfire_cyan",
    blue = "content/fx/particles/rainbow_flame/buff_warpfire_blue",
    violet = "content/fx/particles/rainbow_flame/buff_warpfire_violet",
    pink = "content/fx/particles/rainbow_flame/buff_warpfire_pink",
}
local impact_effect = "content/fx/particles/weapons/flame_staff/psyker_flame_staff_impact_delay"
local impact_presets = {
    { hue = 0, effect = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_red" },
    { hue = 30, effect = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_orange" },
    { hue = 55, effect = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_yellow" },
    { hue = 120, effect = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_green" },
    { hue = 180, effect = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_cyan" },
    { hue = 240, effect = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_blue" },
    { hue = 275, effect = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_violet" },
    { hue = 325, effect = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_pink" },
}
local flamer_impact_effect = "content/fx/particles/weapons/rifles/zealot_flamer/zealot_flamer_impact_delay"
local flamer_impact_presets = {
    { hue = 0, effect = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_red" },
    { hue = 30, effect = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_orange" },
    { hue = 55, effect = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_yellow" },
    { hue = 120, effect = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_green" },
    { hue = 180, effect = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_cyan" },
    { hue = 240, effect = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_blue" },
    { hue = 275, effect = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_violet" },
    { hue = 325, effect = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_pink" },
}
local hsv_parameter = "rainbow_flame_hsv_enable"
local cycle_parameter = "rainbow_flame_cycle"
local enabled = false
local resources_ready = false
local revision = 0
local selected_enemy_effect = enemy_effect
local selected_impact_effect = impact_effect
local selected_flamer_impact_effect = flamer_impact_effect
local staff_profile = { clouds = clouds }
local staff_husk_profile = { clouds = husk_clouds }
local local_profiles = { staff_profile, flamer_profiles[1], flamer_profiles[2] }
local husk_profiles = { staff_husk_profile, flamer_profiles[3] }
local stock_box = QuaternionBox(0, 0, 0, 0)

---@class RainbowFlameParticleState
---@field revision integer
---@field seen integer
---@field profile table?

---@class RainbowFlameOwnerState
---@field generation integer
---@field particles table<integer, RainbowFlameParticleState>

---@type table<FlamerGasEffects, RainbowFlameOwnerState>
local owners = setmetatable({}, { __mode = "k" })

local function enemy_effect_for_settings(color, opacity)
    local preset = enemy_presets[color]
    if opacity == 0 then
        return "content/fx/particles/rainbow_flame/buff_warpfire_hidden"
    elseif not preset then
        if opacity == 100 then
            return enemy_effect
        end
        return "content/fx/particles/rainbow_flame/buff_warpfire_original_opacity_" .. opacity
    elseif opacity == 100 then
        return preset
    end
    return preset .. "_opacity_" .. opacity
end

local function impact_effect_for_hue(hue, presets)
    local selected = presets[1]
    local selected_distance = math.huge
    for i = 1, #presets do
        local preset = presets[i]
        local distance = math.abs(hue - preset.hue)
        distance = math.min(distance, 360 - distance)
        if distance < selected_distance then
            selected = preset
            selected_distance = distance
        end
    end
    return selected.effect
end

local function cache_settings()
    local rainbow = mod:get("rainbow")
    local original = mod:get("original_color") and not rainbow
    local hue = mod:get("hue")
    local flamer_rainbow = mod:get("flamer_rainbow")
    local flamer_original = mod:get("flamer_original_color") and not flamer_rainbow
    local flamer_hue = mod:get("flamer_hue")
    local enemy_color = mod:get("enemy_color")
    local enemy_opacity = mod:get("enemy_opacity")
    local staff_hsv_box = QuaternionBox(hue / 360, mod:get("opacity"), mod:get("brightness"), original and -1 or 1)
    local staff_cycle_box = Vector3Box(rainbow and 1 or 0, mod:get("speed"), 0)
    staff_profile.hsv_box = staff_hsv_box
    staff_profile.cycle_box = staff_cycle_box
    staff_husk_profile.hsv_box = staff_hsv_box
    staff_husk_profile.cycle_box = staff_cycle_box
    local flamer_hsv_box = QuaternionBox(flamer_hue / 360, mod:get("flamer_opacity"), mod:get("flamer_brightness"), flamer_original and -1 or 1)
    local flamer_cycle_box = Vector3Box(flamer_rainbow and 1 or 0, mod:get("flamer_speed"), 0)
    for i = 1, #flamer_profiles do
        flamer_profiles[i].hsv_box = flamer_hsv_box
        flamer_profiles[i].cycle_box = flamer_cycle_box
    end
    selected_enemy_effect = enemy_effect_for_settings(enemy_color, enemy_opacity)
    selected_impact_effect = not original and not rainbow and impact_effect_for_hue(hue, impact_presets) or impact_effect
    selected_flamer_impact_effect = not flamer_original and not flamer_rainbow and impact_effect_for_hue(flamer_hue, flamer_impact_presets) or flamer_impact_effect
    revision = revision + 1
end

---@param owner FlamerGasEffects
---@param particle_id integer
local function particle_profile(owner, particle_id)
    local profiles = owner._is_husk and husk_profiles or local_profiles
    for i = 1, #profiles do
        local profile = profiles[i]
        local matches = true
        for j = 1, #profile.clouds do
            if not World.has_particles_material(owner._world, particle_id, profile.clouds[j]) then
                matches = false
                break
            end
        end
        if matches then
            return profile
        end
    end
end

---@param owner FlamerGasEffects
---@param particle_id integer
---@param state RainbowFlameParticleState
local function apply(owner, particle_id, state)
    local profile = state.profile
    if profile and state.revision ~= revision then
        state.revision = revision
        for i = 1, #profile.clouds do
            World.set_particles_material_vector2(owner._world, particle_id, profile.clouds[i], cycle_parameter, profile.cycle_box:unbox())
            World.set_particles_material_vector4(owner._world, particle_id, profile.clouds[i], hsv_parameter, profile.hsv_box:unbox())
        end
    end
end

---@param owner FlamerGasEffects
---@param state RainbowFlameOwnerState
---@param particle_id integer?
local function visit(owner, state, particle_id)
    if not particle_id then
        return
    end
    local particle = state.particles[particle_id]
    if not particle then
        particle = { revision = -1, seen = 0, profile = particle_profile(owner, particle_id) }
        state.particles[particle_id] = particle
    end
    particle.seen = state.generation
    apply(owner, particle_id, particle)
end

---@param owner FlamerGasEffects
local function update_owner(owner)
    if not enabled or DEDICATED_SERVER then
        return
    end
    local state = owners[owner]
    if not state then
        state = { generation = 0, particles = {} }
        owners[owner] = state
    end
    state.generation = state.generation + 1
    visit(owner, state, owner._stream_effect_id)
    for i = 1, #owner._stoped_particles do
        visit(owner, state, owner._stoped_particles[i])
    end
    for id, particle in pairs(state.particles) do
        if particle.seen ~= state.generation then
            state.particles[id] = nil
        end
    end
end

---@param owner FlamerGasEffects
local function restore_owner(owner)
    local state = owners[owner]
    owners[owner] = nil
    if state and not rawget(owner, "__deleted") then
        for id, particle in pairs(state.particles) do
            local profile = particle.profile
            if profile and World.are_particles_playing(owner._world, id) then
                for i = 1, #profile.clouds do
                    World.set_particles_material_vector4(owner._world, id, profile.clouds[i], hsv_parameter, stock_box:unbox())
                end
            end
        end
    end
end

local function restore_all()
    for owner in pairs(owners) do
        mod:pcall(restore_owner, owner)
    end
end

mod:hook_safe("FlamerGasEffects", "_update_effects", function(self, dt, t)
    update_owner(self)
end)

mod:hook("FlamerGasEffects", "unwield", function(func, self)
    mod:pcall(restore_owner, self)
    return func(self)
end)

mod:hook("FlamerGasEffects", "destroy", function(func, self)
    mod:pcall(restore_owner, self)
    return func(self)
end)

mod:hook("World", "create_particles", function(func, world, effect_name, position, rotation, scale, particle_group)
    if enabled and not DEDICATED_SERVER then
        if effect_name == enemy_effect then
            effect_name = selected_enemy_effect
        elseif effect_name == impact_effect then
            effect_name = selected_impact_effect
        elseif effect_name == flamer_impact_effect then
            effect_name = selected_flamer_impact_effect
        end
    end
    return func(world, effect_name, position, rotation, scale, particle_group)
end)

mod.on_enabled = function()
    cache_settings()
    enabled = resources_ready
end

mod.on_all_mods_loaded = function()
    resources_ready = redirects and redirects.commit() or false
    if resources_ready and mod:is_enabled() then
        cache_settings()
        enabled = true
    end
end

mod.on_disabled = function()
    enabled = false
    restore_all()
end

mod.on_unload = function()
    enabled = false
    restore_all()
    if redirects then
        redirects.clear()
    end
end

mod.on_setting_changed = function()
    if not enabled then
        return
    end
    cache_settings()
    for owner, state in pairs(owners) do
        if not rawget(owner, "__deleted") then
            for id, particle in pairs(state.particles) do
                if World.are_particles_playing(owner._world, id) then
                    apply(owner, id, particle)
                else
                    state.particles[id] = nil
                end
            end
        else
            owners[owner] = nil
        end
    end
end

mod.on_game_state_changed = function(status, state_name)
    if status == "exit" and state_name == "StateGameplay" then
        table.clear(owners)
    end
end
