@echo off
jq ".models | to_entries[] | select(.value.tool_call == true) | {id: .value.id, context: .value.limit.context, output: .value.limit.output, input_cost: .value.cost.input, output_cost: .value.cost.output, structured_output: .value.structured_output}" "S:\federation\nvidia_extract.json"
