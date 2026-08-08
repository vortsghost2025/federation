local key = KEYS[1]
local target_id = ARGV[1]
local items = redis.call("LRANGE", key, 0, -1)
local removed = 0
for i, item in ipairs(items) do
    if string.find(item, target_id, 1, true) then
        redis.call("LREM", key, 1, item)
        removed = removed + 1
    end
end
return removed
