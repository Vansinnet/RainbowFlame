---@class RainbowFlameMod : DMFMod
local mod = get_mod("RainbowFlame")

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
local hsv_parameter = "rainbow_flame_hsv_enable"
local cycle_parameter = "rainbow_flame_cycle"
local enabled = false
local revision = 0
local selected_enemy_effect = enemy_effect
local selected_impact_effect = impact_effect
local hsv_box
local cycle_box
local stock_box = QuaternionBox(0, 0, 0, 0)

---@class RainbowFlameParticleState
---@field revision integer
---@field seen integer
---@field matches boolean

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

local function impact_effect_for_hue(hue)
    local selected = impact_presets[1]
    local selected_distance = math.huge
    for i = 1, #impact_presets do
        local preset = impact_presets[i]
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
    local enemy_color = mod:get("enemy_color")
    local enemy_opacity = mod:get("enemy_opacity")
    hsv_box = QuaternionBox(hue / 360, mod:get("opacity"), mod:get("brightness"), original and -1 or 1)
    cycle_box = Vector3Box(rainbow and 1 or 0, mod:get("speed"), 0)
    selected_enemy_effect = enemy_effect_for_settings(enemy_color, enemy_opacity)
    selected_impact_effect = not original and not rainbow and impact_effect_for_hue(hue) or impact_effect
    revision = revision + 1
end

---@param owner FlamerGasEffects
---@param particle_id integer
---@param state RainbowFlameParticleState
local function apply(owner, particle_id, state)
    if state.matches and state.revision ~= revision then
        state.revision = revision
        local owner_clouds = owner._is_husk and husk_clouds or clouds
        for i = 1, #owner_clouds do
            World.set_particles_material_vector2(owner._world, particle_id, owner_clouds[i], cycle_parameter, cycle_box:unbox())
            World.set_particles_material_vector4(owner._world, particle_id, owner_clouds[i], hsv_parameter, hsv_box:unbox())
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
        local owner_clouds = owner._is_husk and husk_clouds or clouds
        local matches = true
        for i = 1, #owner_clouds do
            if not World.has_particles_material(owner._world, particle_id, owner_clouds[i]) then
                matches = false
                break
            end
        end
        particle = { revision = -1, seen = 0, matches = matches }
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
        local owner_clouds = owner._is_husk and husk_clouds or clouds
        for id, particle in pairs(state.particles) do
            if particle.matches and World.are_particles_playing(owner._world, id) then
                for i = 1, #owner_clouds do
                    World.set_particles_material_vector4(owner._world, id, owner_clouds[i], hsv_parameter, stock_box:unbox())
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
    if not DEDICATED_SERVER then
        if effect_name == enemy_effect then
            effect_name = selected_enemy_effect
        elseif effect_name == impact_effect then
            effect_name = selected_impact_effect
        end
    end
    return func(world, effect_name, position, rotation, scale, particle_group)
end)

mod.on_enabled = function()
    cache_settings()
    enabled = true
end

mod.on_disabled = function()
    enabled = false
    restore_all()
end

mod.on_unload = function()
    enabled = false
    restore_all()
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
