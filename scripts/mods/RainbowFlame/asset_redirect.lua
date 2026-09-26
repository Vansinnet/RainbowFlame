local LIB_VERSION = 2
local INSTANCE_KEY = "__asset_redirect_instance"
local CDEF_TYPE = "AssetRedirect_CDEF"
local DLL_NAME = "asset-redirect.dll"
local TEXT_CAP = 2048
local STATS_CAP = 262144
local TRACE_CAP = 262144

local _G = _G
local rawget = rawget
local rawset = rawset
local ipairs = ipairs
local pairs = pairs
local pcall = pcall
local tostring = tostring
local type = type
local math_floor = math.floor
local string_format = string.format
local string_lower = string.lower
local table_concat = table.concat

local existing = rawget(_G, INSTANCE_KEY)
local takeover = existing == nil or (not existing.committed and existing.core_version < LIB_VERSION)

if existing and existing.committed and LIB_VERSION > existing.core_version and LIB_VERSION > (existing.newer_available or 0) then
	existing.newer_available = LIB_VERSION
end

local instance = existing or {
	core = nil,
	core_version = 0,
	committed = false,
	committing = false,
	native = nil,
	native_state = "pending",
	native_error = nil,
	dll_version = nil,
	late = false,
	files = {},
	order = {},
	arrival = 0,
	candidates = {},
	stock_hashes = {},
	reported = {},
	command_mod = nil,
	newer_available = nil,
}

local facade = {
	register = function(mod, spec)
		return instance.core.register(mod, spec, LIB_VERSION)
	end,
	commit = function()
		return instance.core.commit()
	end,
	state = function(handle)
		return instance.core.state(handle)
	end,
	winner = function(handle)
		return instance.core.winner(handle)
	end,
	clear = function(mod)
		return instance.core.clear(mod)
	end,
	version = function()
		return instance.core.version()
	end,
}

if not takeover then
	return facade
end

rawset(_G, INSTANCE_KEY, instance)

local Mods = rawget(_G, "Mods")
local ffi = Mods and Mods.lua and Mods.lua.ffi
local cjson = rawget(_G, "cjson")

local CDEF = [[
	typedef struct { int unused; } AssetRedirect_CDEF;
	int AssetRedirect_Version(char* out, int cap);
	int AssetRedirect_Install(char* err, int errlen);
	int AssetRedirect_Add(const char* stock_rel, const char* replacement, const char* expect_stock_sha256, char* err, int errlen);
	int AssetRedirect_AddNew(const char* virtual_rel, const char* replacement, char* err, int errlen);
	int AssetRedirect_Remove(const char* stock_rel);
	int AssetRedirect_Opens(const char* stock_rel);
	int AssetRedirect_HashFile(const char* path, char* out, int cap);
	int AssetRedirect_Stats(char* out, int cap);
	int AssetRedirect_TraceEnable(int on);
	int AssetRedirect_TraceDump(char* out, int cap);
]]

local MODULE_CDEF = "void* GetModuleHandleA(const char* name);"

local STATE_ORDER = { "active", "shared", "compatible", "displaced", "refused", "restart_required", "unavailable", "pending" }

local core = {}

local function text_buffer(size)
	return ffi.new("char[?]", size)
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

local function note_candidate(mod, copy_version)
	local folder = mod_folder(mod)

	for _, candidate in ipairs(instance.candidates) do
		if candidate.folder == folder then
			candidate.mod = mod

			if copy_version > candidate.version then
				candidate.version = copy_version
			end

			return candidate
		end
	end

	local candidate = { folder = folder, version = copy_version, mod = mod }

	instance.candidates[#instance.candidates + 1] = candidate

	return candidate
end

local function hash_file(path)
	local out = text_buffer(TEXT_CAP)

	if instance.native.AssetRedirect_HashFile(path, out, TEXT_CAP) == 1 then
		return string_lower(ffi.string(out))
	end

	return nil, ffi.string(out)
end

local function seed_from_stats()
	local out = text_buffer(STATS_CAP)

	if instance.native.AssetRedirect_Stats(out, STATS_CAP) ~= 1 or not cjson then
		return
	end

	local stats = cjson.decode(ffi.string(out))
	local entries = type(stats) == "table" and stats.entries

	if type(entries) ~= "table" then
		return
	end

	for _, entry in ipairs(entries) do
		if type(entry.key) == "string" and type(entry.replacement) == "string" and entry.virtual ~= true then
			local hash = hash_file(entry.replacement)

			if hash then
				file_record(entry.key).pushed = { path = entry.replacement, hash = hash }
			end
		end
	end
end

local function fail_native(mod, reason)
	instance.native_state = "unavailable"
	instance.native_error = reason

	mod:error("Asset Redirect could not load its library, so replacement files are off this session: %s", reason)
end

local function load_native(candidate)
	local mod = candidate.mod

	if not ffi then
		fail_native(mod, "Mods.lua.ffi is unavailable")

		return
	end

	if not pcall(ffi.typeof, CDEF_TYPE) then
		ffi.cdef(CDEF)
	end

	if not pcall(function() return ffi.C.GetModuleHandleA end) then
		ffi.cdef(MODULE_CDEF)
	end

	local path = "../mods/" .. candidate.folder .. "/bin/" .. DLL_NAME

	if ffi.C.GetModuleHandleA(DLL_NAME) ~= nil then
		instance.late = true
		path = DLL_NAME
	end

	local ok, lib = pcall(ffi.load, path)

	if not ok then
		fail_native(mod, tostring(lib))

		return
	end

	local err = text_buffer(TEXT_CAP)

	if lib.AssetRedirect_Install(err, TEXT_CAP) ~= 1 then
		fail_native(mod, ffi.string(err))

		return
	end

	instance.native = lib
	instance.native_state = "ready"

	local version = text_buffer(64)

	if lib.AssetRedirect_Version(version, 64) == 1 then
		instance.dll_version = ffi.string(version)
	end

	if instance.late then
		seed_from_stats()
	end
end

local function report(reg, reason)
	local key = reg.owner .. "|" .. reg.stock .. "|" .. reason

	if instance.reported[key] then
		return
	end

	instance.reported[key] = true

	reg.mod:info("Asset Redirect left %s stock: %s", reg.stock, reason)
end

local function refuse(reg, reason)
	reg.valid = false
	reg.reason = reason

	report(reg, reason)
end

local function bad_relative(path)
	return type(path) ~= "string" or path == "" or path:sub(1, 1) == "/" or path:find("\\", 1, true) ~= nil or path:find("..", 1, true) ~= nil
end

local function field_error(spec)
	if type(spec) ~= "table" then
		return "the registration is not a table"
	end

	if bad_relative(spec.stock) or spec.stock ~= string_lower(spec.stock) then
		return "stock must be a lowercase path under bundle with forward slashes"
	end

	if bad_relative(spec.file) then
		return "file must be a path inside the mod folder with forward slashes"
	end

	if spec.virtual == true then
		if spec.sha256 ~= nil then
			return "a virtual registration has no stock file, so it takes no sha256"
		end
	elseif type(spec.sha256) ~= "string" or #spec.sha256 ~= 64 or spec.sha256:find("^%x+$") == nil then
		return "sha256 must be 64 hex digits"
	end

	if spec.virtual ~= nil and type(spec.virtual) ~= "boolean" then
		return "virtual must be true or false"
	end

	if spec.priority ~= nil and (type(spec.priority) ~= "number" or spec.priority ~= math_floor(spec.priority)) then
		return "priority must be a whole number"
	end

	if spec.contract ~= nil and (type(spec.contract) ~= "string" or spec.contract == "") then
		return "contract must be a non-empty string"
	end

	return nil
end

local function stock_hash(stock)
	local cached = instance.stock_hashes[stock]

	if cached then
		return cached
	end

	local hash, err = hash_file("bundle/" .. stock)

	if hash then
		instance.stock_hashes[stock] = hash
	end

	return hash, err
end

local function evaluate(reg)
	local spec = reg.spec
	local reason = field_error(spec)

	if reason then
		return reason
	end

	if spec.virtual ~= true then
		local expected = string_lower(spec.sha256)
		local actual, err = stock_hash(spec.stock)

		if not actual then
			return "cannot read the stock file: " .. tostring(err)
		end

		if actual ~= expected then
			return string_format("the stock file has changed (sha256 %s, expected %s)", actual, expected)
		end
	end

	local payload = "mods/" .. mod_folder(reg.mod) .. "/" .. spec.file
	local hash, payload_err = hash_file(payload)

	if not hash then
		return "cannot read the payload: " .. tostring(payload_err)
	end

	reg.payload_path = payload
	reg.payload_hash = hash

	return nil
end

local function validate(reg)
	reg.valid = false
	reg.reason = nil
	reg.payload_path = nil
	reg.payload_hash = nil

	local reason = evaluate(reg)

	if reason then
		refuse(reg, reason)
	else
		reg.valid = true
	end
end

local function pick_winner(file)
	local best

	for _, reg in ipairs(file.regs) do
		if reg.valid and (not best or reg.priority > best.priority or (reg.priority == best.priority and reg.arrival < best.arrival)) then
			best = reg
		end
	end

	return best
end

local function resolve(stock)
	local file = instance.files[stock]
	local native = instance.native

	for _ = 1, #file.regs + 1 do
		local winner = pick_winner(file)
		local pushed = file.pushed
		local target_hash = winner and winner.payload_hash
		local pushed_hash = pushed and pushed.hash

		if target_hash == pushed_hash then
			file.winner = winner

			return
		end

		if native.AssetRedirect_Opens(stock) > 0 or (pushed == nil and (instance.committed or instance.late)) then
			file.restart = true
		end

		if not winner then
			native.AssetRedirect_Remove(stock)
			file.pushed = nil
			file.winner = nil

			return
		end

		local err = text_buffer(TEXT_CAP)

		local added

		if winner.spec.virtual == true then
			added = native.AssetRedirect_AddNew(stock, winner.payload_path, err, TEXT_CAP)
		else
			added = native.AssetRedirect_Add(stock, winner.payload_path, winner.expect, err, TEXT_CAP)
		end

		if added == 1 then
			file.pushed = { path = winner.payload_path, hash = target_hash }
			file.winner = winner

			return
		end

		refuse(winner, ffi.string(err))
	end
end

function core.commit()
	if instance.committed or instance.committing then
		return
	end

	instance.committing = true

	local best

	for _, candidate in ipairs(instance.candidates) do
		if not best or candidate.version > best.version then
			best = candidate
		end
	end

	if best and instance.native_state == "pending" then
		load_native(best)
	end

	if instance.native_state == "ready" then
		for _, stock in ipairs(instance.order) do
			for _, reg in ipairs(instance.files[stock].regs) do
				validate(reg)
			end

			resolve(stock)
		end
	end

	instance.committing = false
	instance.committed = true
end

function core.state(reg)
	if not instance.committed then
		return "pending"
	end

	if instance.native_state ~= "ready" then
		return "unavailable"
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

	if winner.payload_hash == reg.payload_hash then
		return "shared"
	end

	if reg.contract and reg.contract == winner.contract then
		return "compatible"
	end

	return "displaced"
end

function core.winner(reg)
	local file = instance.files[reg.stock]
	local winner = file and file.winner

	if not winner then
		return nil
	end

	return winner.owner, winner.contract
end

local function print_status(mod)
	core.commit()

	local native = instance.native
	local counts = {}

	for _, stock in ipairs(instance.order) do
		local file = instance.files[stock]
		local parts = {}

		for _, reg in ipairs(file.regs) do
			local state = core.state(reg)

			counts[state] = (counts[state] or 0) + 1
			parts[#parts + 1] = string_format("%s=%s", reg.owner, state)
		end

		local opens = native and native.AssetRedirect_Opens(stock) or -1
		local winner = file.winner and file.winner.owner or "none"

		mod:info("%s winner=%s opens=%d %s", stock, winner, opens, table_concat(parts, " "))
	end

	local summary = {}

	for _, state in ipairs(STATE_ORDER) do
		if counts[state] then
			summary[#summary + 1] = string_format("%s %d", state, counts[state])
		end
	end

	mod:echo("%s", string_format("Asset Redirect %d, DLL %s: %d files, %s. Details are in the log.", LIB_VERSION, tostring(instance.dll_version), #instance.order, #summary > 0 and table_concat(summary, ", ") or "no registrations"))

	if instance.newer_available then
		mod:echo("%s", string_format("A newer Asset Redirect (library %d) is installed. It takes over after a restart.", instance.newer_available))
	end

	if instance.native_error then
		mod:echo("%s", "Asset Redirect library error: " .. instance.native_error)
	end
end

local function trace_command(mod, choice)
	core.commit()

	local native = instance.native

	if not native then
		mod:echo("%s", "Asset Redirect library is not loaded.")

		return
	end

	if choice == "on" or choice == "off" then
		native.AssetRedirect_TraceEnable(choice == "on" and 1 or 0)
		mod:echo("%s", "Asset Redirect trace " .. choice .. ".")

		return
	end

	if choice == "dump" then
		local out = text_buffer(TRACE_CAP)
		local length = native.AssetRedirect_TraceDump(out, TRACE_CAP)

		if length >= TRACE_CAP then
			out = text_buffer(length + 1)
			length = native.AssetRedirect_TraceDump(out, length + 1)
		end

		if length < 0 then
			mod:echo("%s", "Asset Redirect trace dump failed.")

			return
		end

		mod:info("trace %s", ffi.string(out))
		mod:echo("%s", "Asset Redirect trace written to the log.")

		return
	end

	mod:echo("%s", "Usage: /asset_redirect trace on|off|dump")
end

function core.command(sub, choice)
	local mod = instance.command_mod

	if sub == "trace" then
		trace_command(mod, choice)

		return
	end

	print_status(mod)
end

local function ensure_command(mod)
	local current = instance.command_mod
	local get_mod = rawget(_G, "get_mod")

	if current and get_mod and get_mod(current:get_name()) == current then
		return
	end

	instance.command_mod = mod

	mod:command("asset_redirect", "Asset Redirect: list redirected files and their states. Add trace on, trace off or trace dump for the file trace.", function(...)
		return instance.core.command(...)
	end)
end

function core.register(mod, spec, copy_version)
	local owner = mod:get_name()
	local is_table = type(spec) == "table"
	local stock = is_table and type(spec.stock) == "string" and spec.stock or "?"
	local file = file_record(stock)
	local reg

	for _, candidate in ipairs(file.regs) do
		if candidate.owner == owner then
			reg = candidate

			break
		end
	end

	if not reg then
		instance.arrival = instance.arrival + 1
		reg = { owner = owner, stock = stock, arrival = instance.arrival, valid = false }
		file.regs[#file.regs + 1] = reg
	end

	reg.mod = mod
	reg.spec = spec
	reg.priority = is_table and type(spec.priority) == "number" and spec.priority or 0
	reg.contract = is_table and spec.contract or nil
	reg.expect = is_table and type(spec.sha256) == "string" and string_lower(spec.sha256) or nil

	local candidate = note_candidate(mod, copy_version)

	ensure_command(mod)

	if not instance.committed then
		return reg
	end

	if instance.native_state == "pending" then
		load_native(candidate)
	end

	if instance.native_state == "ready" then
		validate(reg)
		resolve(stock)
	end

	return reg
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

instance.core = core
instance.core_version = LIB_VERSION

return facade
