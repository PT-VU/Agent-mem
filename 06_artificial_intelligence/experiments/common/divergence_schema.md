# divergence_report.json schema (v1)

## root
- `report_version`: string
- `generated_at`: ISO8601 string
- `inputs`: object
- `coverage`: object
- `summary`: object
- `detour_reduction_top`: array of `per_instance_item`
- `detour_regression_top`: array of `per_instance_item`
- `memory_intervention_points`: array of object
- `mem_unique_failures_top`: array of `per_instance_item`
- `effective_interventions_top`: array of `per_instance_item`
- `per_instance`: array of `per_instance_item`
- `assumptions`: array of string

## inputs
- `with_mem_dir`: string
- `no_mem_dir`: string

## coverage
- `with_mem_instances`: integer
- `no_mem_instances`: integer
- `paired_instances`: integer
- `with_only_instances`: string[]
- `no_only_instances`: string[]

## summary
- `avg_step_delta_no_minus_with`: number
- `avg_fail_signal_delta_no_minus_with`: number
- `improved_instances`: integer
- `regressed_instances`: integer
- `equal_instances`: integer
- `instances_with_mem_injection_detected`: integer
- `divergence_explainable_by_injection`: integer
- `mem_unique_failures`: integer
- `effective_interventions`: integer
- `effective_intervention_rate`: number
- `divergence_explainable_ratio`: number

## per_instance_item
- `instance_id`: string
- `with_mem_steps`: integer
- `no_mem_steps`: integer
- `step_delta_no_minus_with`: integer
- `detour_reduction`: integer
- `detour_increase`: integer
- `with_mem_exit_status`: string
- `no_mem_exit_status`: string
- `with_mem_success`: boolean
- `no_mem_success`: boolean
- `first_divergence_step`: integer or null
- `with_mem_injection_steps`: integer[]
- `injection_before_or_at_divergence`: boolean
- `effective_intervention`: boolean
- `mem_unique_failure`: boolean
- `with_mem_fail_signal_count`: integer
- `no_mem_fail_signal_count`: integer
- `fail_signal_delta_no_minus_with`: integer

## memory_intervention_points item
- `instance_id`: string
- `first_divergence_step`: integer or null
- `with_mem_injection_steps`: integer[]
- `detour_reduction`: integer
- `effective_intervention`: boolean
