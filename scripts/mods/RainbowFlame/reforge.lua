-- Reforge Lua library: shares one copy of reforge.dll between every mod that
-- ships it, decides which mod wins when several replace the same game file,
-- and reports per-file state.
--
-- Ship this file as scripts/mods/<Mod>/reforge.lua and reforge.dll as
-- <Mod>/bin/reforge.dll, then:
--
--   local reforge = mod:io_dofile("<Mod>/scripts/mods/<Mod>/reforge")
--   local handles = reforge.register_manifest(mod, "<Mod>/scripts/mods/<Mod>/reforge_manifest")
--   mod.on_all_mods_loaded = function() reforge.commit() end
--
-- MIT licence. https://github.com/Vansinnet/Reforge

local LIB_VERSION = 1
local INSTANCE_KEY = "__reforge_instance"
local DLL_NAME = "reforge.dll"
local ABI = 1
local ERR_CAP = 2048

local rawget = rawget
local rawset = rawset
local ipairs = ipairs
local pairs = pairs
local pcall = pcall
local tostring = tostring
local type = type
local string_format = string.format
local table_concat = table.concat
local table_sort = table.sort

local SERVED = { active = true, shared = true, compatible = true }
local STATE_ORDER = { "active", "shared", "compatible", "displaced", "refused", "restart_required", "unavailable", "pending" }

local CDEF = [[
	int Reforge_Abi(void);
	int Reforge_Version(char* out, int cap);
	int Reforge_Install(char* err, int errlen);
	int Reforge_Add(const char* stock_rel, const char* replacement_rel, const char* expect_stock_sha256, char* err, int errlen);
	int Reforge_AddNew(const char* virtual_rel, const char* replacement_rel, char* err, int errlen);
	int Reforge_Remove(const char* stock_rel);
	int Reforge_Clear(void);
	int Reforge_Opens(const char* stock_rel);
	int Reforge_HashFile(const char* rel, char* out, int cap);
	int Reforge_SetEnabled(int on);
	int Reforge_Stats(char* out, int cap);
	int Reforge_TraceEnable(int on);
	int Reforge_TraceDump(char* out, int cap);
]]

-- Shared, version-stable data. Newer library copies may replace `core`, but
-- must keep reading this layout.
local instance = rawget(_G, INSTANCE_KEY)

if not instance then
	instance = {
		core = nil,
		core_version = 0,
		committed = false,
		native = nil,
		native_state = "pending",
		native_error = nil,
		dll_version = nil,
		files = {},
		order = {},
		arrival = 0,
		carriers = {},
		payload_hashes = {},
		reported = {},
		command_owner = nil,
		newer_available = nil,
	}
	rawset(_G, INSTANCE_KEY, instance)
end

local facade = {}

for _, name in ipairs({ "register", "register_manifest", "commit", "state", "reason", "winner", "clear", "version", "set_enabled", "status" }) do
	facade[name] = function(...)
		return instance.core[name](...)
	end
end

facade.served = function(state)
	return SERVED[state] == true
end

local takes_over = instance.core == nil or (not instance.committed and instance.core_version < LIB_VERSION)

if not takes_over then
	if LIB_VERSION > instance.core_version and LIB_VERSION > (instance.newer_available or 0) then
		instance.newer_available = LIB_VERSION
	end

	return facade
end

local core = {}

local function ffi_lib()
	local mods = rawget(_G, "Mods")

	return mods and mods.lua and mods.lua.ffi
end

local function mod_folder(mod)
	return mod:get_internal_data("load_order_name") or mod:get_name()
end

local function file_record(stock)
	local file = instance.files[stock]

	if not file then
		file = { regs = {}, pushed = nil, winner = nil, restart = false }
		instance.files[stock] = file
		instance.order[#instance.order + 1] = stock
	end

	return file
end

local function note_carrier(mod)
	local folder = mod_folder(mod)

	for _, carrier in ipairs(instance.carriers) do
		if carrier.folder == folder then
			carrier.mod = mod

			if LIB_VERSION > carrier.version then
				carrier.version = LIB_VERSION
			end

			return
		end
	end

	instance.carriers[#instance.carriers + 1] = { folder = folder, version = LIB_VERSION, mod = mod }
end

-- Native library ------------------------------------------------------------

local unpack = unpack or table.unpack
local select = select

-- Calls fn(args..., buffer, cap) and returns its result and the buffer text.
local function text_call(fn, cap, ...)
	local ffi = ffi_lib()
	local buf = ffi.new("char[?]", cap)
	local n = select("#", ...)
	local args = { ... }

	args[n + 1] = buf
	args[n + 2] = cap

	local ok = fn(unpack(args, 1, n + 2))

	return ok, ffi.string(buf)
end

local function load_from(ffi, path)
	local ok, lib = pcall(ffi.load, path)

	if not ok then
		return nil, tostring(lib)
	end

	local abi_ok, abi = pcall(function()
		return lib.Reforge_Abi()
	end)

	if not abi_ok or abi ~= ABI then
		return nil, string_format("%s has ABI %s, this library needs %d", path, tostring(abi), ABI)
	end

	local installed, err = text_call(lib.Reforge_Install, ERR_CAP)

	if installed ~= 1 then
		return nil, err
	end

	return lib
end

local function load_native()
	local ffi = ffi_lib()
	local first = instance.carriers[1] and instance.carriers[1].mod

	if not ffi then
		instance.native_state = "unavailable"
		instance.native_error = "Mods.lua.ffi is unavailable"
	else
		if not instance.cdef_done then
			-- pcall: a hot reload may meet declarations from an earlier run.
			pcall(ffi.cdef, CDEF)
			pcall(ffi.cdef, "void* GetModuleHandleA(const char* name);")
			instance.cdef_done = true
		end

		local candidates = {}

		if ffi.C.GetModuleHandleA(DLL_NAME) ~= nil then
			candidates[1] = DLL_NAME
		end

		local carriers = {}

		for i, carrier in ipairs(instance.carriers) do
			carriers[i] = carrier
		end

		table_sort(carriers, function(a, b)
			return a.version > b.version
		end)

		for _, carrier in ipairs(carriers) do
			candidates[#candidates + 1] = "../mods/" .. carrier.folder .. "/bin/" .. DLL_NAME
		end

		local errors = {}

		for _, path in ipairs(candidates) do
			local lib, err = load_from(ffi, path)

			if lib then
				instance.native = lib
				instance.native_state = "ready"
				instance.native_error = nil

				local vok, version = text_call(lib.Reforge_Version, 64)
				instance.dll_version = vok == 1 and version or "?"

				return
			end

			errors[#errors + 1] = err
		end

		instance.native_state = "unavailable"
		instance.native_error = #errors > 0 and table_concat(errors, "; ") or "no mod ships bin/" .. DLL_NAME
	end

	if first then
		first:error("Reforge could not load reforge.dll, so replacement files are off this session: %s", instance.native_error)
	end
end

-- Registrations -------------------------------------------------------------

local function report(reg, message)
	local key = reg.owner .. "|" .. reg.stock .. "|" .. message

	if not instance.reported[key] then
		instance.reported[key] = true
		reg.mod:info("Reforge left %s stock: %s", reg.stock, message)
	end
end

local function payload_rel(reg)
	return "mods/" .. mod_folder(reg.mod) .. "/" .. reg.spec.file
end

local function payload_hash(reg)
	local rel = payload_rel(reg)
	local cached = instance.payload_hashes[rel]

	if cached then
		return cached
	end

	local ok, out = text_call(instance.native.Reforge_HashFile, ERR_CAP, rel)

	if ok == 1 then
		instance.payload_hashes[rel] = out

		return out
	end

	return nil
end

local function spec_error(spec)
	if type(spec) ~= "table" then
		return "the registration is not a table"
	end

	if type(spec.stock) ~= "string" or spec.stock:sub(1, 7) ~= "bundle/" then
		return "stock must be a game path starting with bundle/"
	end

	if type(spec.file) ~= "string" or spec.file == "" then
		return "file must be a path inside the mod folder"
	end

	if spec.virtual ~= nil and type(spec.virtual) ~= "boolean" then
		return "virtual must be true or false"
	end

	if spec.virtual ~= true and type(spec.sha256) ~= "string" then
		return "sha256 of the stock file is required unless virtual = true"
	end

	if spec.priority ~= nil and (type(spec.priority) ~= "number" or spec.priority % 1 ~= 0) then
		return "priority must be a whole number"
	end

	if spec.contract ~= nil and (type(spec.contract) ~= "string" or spec.contract == "") then
		return "contract must be a non-empty string"
	end

	return nil
end

local function pick_winner(file, skip)
	local best

	for _, reg in ipairs(file.regs) do
		if reg.valid and not skip[reg] and (not best or reg.priority > best.priority or (reg.priority == best.priority and reg.arrival < best.arrival)) then
			best = reg
		end
	end

	return best
end

-- The game keeps what it loaded. `loaded` is the payload (false = stock) that
-- was being served when the file was first seen opened; a restart is needed
-- only while the served payload differs from it.
local function settle(file, opened)
	if opened then
		file.restart = (file.pushed or false) ~= file.loaded
	else
		file.loaded = nil
		file.restart = false
	end
end

-- Pushes the best valid registration for `stock` to the DLL. The DLL checks
-- the stock SHA-256 and all paths; a refused candidate is skipped and the next
-- one tried.
local function resolve(stock)
	local file = instance.files[stock]
	local native = instance.native
	local skip = {}

	if not native then
		return
	end

	local opened = native.Reforge_Opens(stock) > 0

	if opened and file.loaded == nil then
		file.loaded = file.pushed or false
	end

	while true do
		local winner = pick_winner(file, skip)
		local target = winner and payload_rel(winner)

		if target == file.pushed then
			file.winner = winner

			return settle(file, opened)
		end

		if not winner then
			native.Reforge_Remove(stock)
			file.pushed = nil
			file.winner = nil

			return settle(file, opened)
		end

		local ok, err

		if winner.spec.virtual == true then
			ok, err = text_call(native.Reforge_AddNew, ERR_CAP, stock, target)
		else
			ok, err = text_call(native.Reforge_Add, ERR_CAP, stock, target, winner.spec.sha256)
		end

		if ok == 1 then
			file.pushed = target
			file.winner = winner

			return settle(file, opened)
		end

		winner.valid = false
		winner.reason = err
		skip[winner] = true
		report(winner, err)
	end
end

-- Polychromatic and other mods may ship Wobin's Asset Redirect, a separate
-- hooking DLL. Two hooks serving the same file would race, so a file that
-- Asset Redirect also serves is left to it and reported as displaced.
local function asset_redirect_owner(stock)
	local other = rawget(_G, "__asset_redirect_instance")
	local files = type(other) == "table" and other.files

	if type(files) ~= "table" or type(stock) ~= "string" then
		return nil
	end

	local file = files[stock:sub(8)]
	local regs = type(file) == "table" and file.regs

	if type(regs) ~= "table" then
		return nil
	end

	for _, reg in ipairs(regs) do
		if type(reg) == "table" and reg.owner ~= nil then
			return tostring(reg.owner)
		end
	end

	return nil
end

local function validate(reg)
	local reason = spec_error(reg.spec)

	reg.foreign = nil

	if not reason then
		local owner = asset_redirect_owner(reg.stock)

		if owner then
			reg.foreign = owner
			reason = "also replaced by " .. owner .. " through Asset Redirect; left to it"
		end
	end

	reg.valid = reason == nil
	reg.reason = reason

	if reason then
		report(reg, reason)
	end
end

function core.register(mod, spec)
	local owner = mod:get_name()
	local stock = type(spec) == "table" and type(spec.stock) == "string" and spec.stock or "?"
	local file = file_record(stock)
	local reg

	for _, existing in ipairs(file.regs) do
		if existing.owner == owner then
			reg = existing

			break
		end
	end

	if not reg then
		instance.arrival = instance.arrival + 1
		reg = { owner = owner, stock = stock, arrival = instance.arrival }
		file.regs[#file.regs + 1] = reg
	end

	reg.mod = mod
	reg.spec = spec
	reg.priority = type(spec) == "table" and spec.priority or 0
	reg.contract = type(spec) == "table" and spec.contract or nil

	note_carrier(mod)
	core.ensure_command(mod)

	if instance.committed then
		if instance.native_state == "pending" then
			load_native()
		end

		if instance.native_state == "ready" then
			validate(reg)
			resolve(stock)
		end
	end

	return reg
end

function core.register_manifest(mod, path_or_table)
	local manifest = path_or_table

	if type(manifest) == "string" then
		manifest = mod:io_dofile(manifest)
	end

	local handles = {}

	if type(manifest) ~= "table" or manifest.schema ~= 1 or type(manifest.redirects) ~= "table" then
		mod:error("Reforge: %s is not a schema 1 manifest", tostring(path_or_table))

		return handles
	end

	for i, spec in ipairs(manifest.redirects) do
		handles[i] = core.register(mod, spec)
	end

	return handles
end

function core.commit()
	if instance.committed then
		return
	end

	instance.committed = true

	if instance.native_state == "pending" and #instance.order > 0 then
		load_native()
	end

	if instance.native_state ~= "ready" then
		return
	end

	for _, stock in ipairs(instance.order) do
		for _, reg in ipairs(instance.files[stock].regs) do
			validate(reg)
		end

		resolve(stock)
	end
end

function core.state(reg)
	if type(reg) ~= "table" then
		return "refused"
	end

	if not instance.committed then
		return "pending"
	end

	if instance.native_state ~= "ready" then
		return "unavailable"
	end

	if reg.foreign then
		return "displaced"
	end

	if not reg.valid then
		return "refused"
	end

	local file = instance.files[reg.stock]

	if file.restart then
		return "restart_required"
	end

	local winner = file.winner

	if winner == reg then
		return "active"
	end

	if not winner then
		return "refused"
	end

	local mine = payload_hash(reg)

	if mine and mine == payload_hash(winner) then
		return "shared"
	end

	if reg.contract and reg.contract == winner.contract then
		return "compatible"
	end

	return "displaced"
end

function core.reason(reg)
	return type(reg) == "table" and reg.reason or nil
end

function core.winner(reg)
	if type(reg) == "table" and reg.foreign then
		return reg.foreign, nil
	end

	local file = type(reg) == "table" and instance.files[reg.stock]
	local winner = file and file.winner

	if winner then
		return winner.owner, winner.contract
	end

	return nil
end

function core.clear(mod)
	local owner = mod:get_name()

	for stock, file in pairs(instance.files) do
		local kept = {}

		for _, reg in ipairs(file.regs) do
			if reg.owner ~= owner then
				kept[#kept + 1] = reg
			end
		end

		if #kept ~= #file.regs then
			file.regs = kept

			if instance.committed and instance.native_state == "ready" then
				resolve(stock)
			end
		end
	end
end

function core.version()
	return LIB_VERSION, instance.dll_version
end

-- Turns every redirect on or off for files opened from now on. Returns the
-- previous state, or nil when the DLL is not loaded.
function core.set_enabled(on)
	if instance.native_state ~= "ready" then
		return nil
	end

	return instance.native.Reforge_SetEnabled(on and 1 or 0) == 1
end

function core.status()
	local counts = {}
	local rows = {}

	for _, stock in ipairs(instance.order) do
		local file = instance.files[stock]
		local parts = {}

		for _, reg in ipairs(file.regs) do
			local state = core.state(reg)

			counts[state] = (counts[state] or 0) + 1
			parts[#parts + 1] = reg.owner .. "=" .. state
		end

		local opens = instance.native and instance.native.Reforge_Opens(stock) or -1

		rows[#rows + 1] = string_format("%s winner=%s opens=%d %s", stock, file.winner and file.winner.owner or "none", opens, table_concat(parts, " "))
	end

	local summary = {}

	for _, state in ipairs(STATE_ORDER) do
		if counts[state] then
			summary[#summary + 1] = state .. " " .. counts[state]
		end
	end

	return {
		lib_version = LIB_VERSION,
		dll_version = instance.dll_version,
		native_state = instance.native_state,
		native_error = instance.native_error,
		files = #instance.order,
		summary = #summary > 0 and table_concat(summary, ", ") or "no registrations",
		rows = rows,
		newer_available = instance.newer_available,
	}
end

local function read_sized(fn)
	local ffi = ffi_lib()
	local need = fn(nil, 0)

	if need < 0 then
		return nil
	end

	local buf = ffi.new("char[?]", need + 1)

	fn(buf, need + 1)

	return ffi.string(buf)
end

function core.command(sub, choice)
	local mod = instance.command_owner

	core.commit()

	if sub == "trace" then
		local native = instance.native

		if not native then
			mod:echo("Reforge: reforge.dll is not loaded.")
		elseif choice == "on" or choice == "off" then
			native.Reforge_TraceEnable(choice == "on" and 1 or 0)
			mod:echo("Reforge trace %s.", choice)
		elseif choice == "dump" then
			mod:info("Reforge trace:\n%s", read_sized(native.Reforge_TraceDump) or "")
			mod:echo("Reforge trace written to the log.")
		else
			mod:echo("Usage: /reforge trace on|off|dump")
		end

		return
	end

	if sub == "on" or sub == "off" then
		local previous = core.set_enabled(sub == "on")

		mod:echo(previous == nil and "Reforge: reforge.dll is not loaded." or "Reforge redirects %s for files opened from now on.", sub)

		return
	end

	local status = core.status()

	for _, row in ipairs(status.rows) do
		mod:info("%s", row)
	end

	mod:echo("Reforge %d, DLL %s: %d files, %s. Details are in the log.", status.lib_version, tostring(status.dll_version), status.files, status.summary)

	if status.native_error then
		mod:echo("Reforge DLL error: %s", status.native_error)
	end

	if status.newer_available then
		mod:echo("A newer Reforge library (%d) is installed and takes over after a restart.", status.newer_available)
	end
end

function core.ensure_command(mod)
	local current = instance.command_owner
	local get_mod = rawget(_G, "get_mod")

	if current and get_mod and get_mod(current:get_name()) == current then
		return
	end

	instance.command_owner = mod

	mod:command("reforge", "Reforge: list replaced game files and their state. Add on/off, or trace on|off|dump.", function(...)
		return instance.core.command(...)
	end)
end

instance.core = core
instance.core_version = LIB_VERSION

return facade
