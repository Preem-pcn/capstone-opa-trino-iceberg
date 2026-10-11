package trino

import rego.v1

# Self-asserted usernames are for this local authorization demo only.
default allow := false

privileged_users := {"admin", "dagster", "publication_lab"}
analyst_users := {"safety_analyst", "operations_analyst", "engineering_analyst"}

# New tables require an explicit policy decision. Metadata tables ($files,
# $snapshots, etc.) and publication histories are not on this allowlist.
silver_tables := {"flights", "rate_0p25hz", "rate_0p5hz", "rate_1hz", "rate_2hz", "rate_4hz", "rate_7hz", "rate_8hz"}
gold_tables := {"flight_events", "flight_phases", "flight_summary"}
silver_schemas := {"silver", "opa_demo_silver"}
gold_schemas := {"gold", "opa_demo_gold"}

table_allowed(table) if {
    table.catalogName == "iceberg"
    table.schemaName in silver_schemas
    table.tableName in silver_tables
}

table_allowed(table) if {
    table.catalogName == "iceberg"
    table.schemaName in gold_schemas
    table.tableName in gold_tables
}

allow if {
    input.context.identity.user in privileged_users
}

allow if {
    input.context.identity.user in analyst_users
    input.action.operation == "ExecuteQuery"
}

allow if {
    input.context.identity.user in analyst_users
    input.action.operation in {"AccessCatalog", "FilterCatalogs", "ShowSchemas"}
    input.action.resource.catalog.name == "iceberg"
}

allow if {
    input.context.identity.user in analyst_users
    input.action.operation in {"FilterSchemas", "ShowTables"}
    schema := input.action.resource.schema
    schema.catalogName == "iceberg"
    schema.schemaName in silver_schemas | gold_schemas
}

allow if {
    input.context.identity.user in analyst_users
    input.action.operation in {"ExecuteFunction", "FilterFunctions", "ShowFunctions"}
    function := input.action.resource.function
    function.catalogName == "system"
    function.schemaName == "builtin"
}

column_denied if {
    input.context.identity.user == "operations_analyst"
    table := input.action.resource.table
    table.schemaName in gold_schemas
    table.tableName == "flight_summary"
    "touchdown_peak_g" in table.columns
}

column_denied if {
    input.context.identity.user in analyst_users
    some column in input.action.resource.table.columns
    startswith(column, "$")
}

allow if {
    input.context.identity.user in analyst_users
    input.action.operation in {"SelectFromColumns", "FilterTables", "ShowColumns", "FilterColumns"}
    table_allowed(input.action.resource.table)
    not column_denied
}

# SHOW/DESCRIBE are rewritten into these metadata queries. Trino applies the
# FilterSchemas/FilterTables/FilterColumns decisions to the objects listed here.
allow if {
    input.context.identity.user in analyst_users
    input.action.operation in {"SelectFromColumns", "ShowColumns", "FilterColumns"}
    table := input.action.resource.table
    table.catalogName == "iceberg"
    table.schemaName == "information_schema"
    table.tableName in {"schemata", "tables", "columns"}
}

# Department scopes: Engineering owns HS-THJ; Operations handles VTBS flights.
scope_predicate := "tail = 'HS-THJ'" if {
    input.context.identity.user == "engineering_analyst"
}

scope_predicate := "origin = 'VTBS' OR destination = 'VTBS'" if {
    input.context.identity.user == "operations_analyst"
}

lookup_schema(schema) := "opa_demo_silver" if {
    schema in {"opa_demo_silver", "opa_demo_gold"}
}

lookup_schema(schema) := "silver" if {
    schema in {"silver", "gold"}
}

rowFilters contains {"expression": scope_predicate, "identity": "admin"} if {
    table := input.action.resource.table
    table_allowed(table)
    table.schemaName in silver_schemas
    table.tableName == "flights"
}

# Filters evaluate before masks, using the internal admin identity. The lookup
# does not recursively receive the requesting analyst's filters.
rowFilters contains {"expression": expression, "identity": "admin"} if {
    table := input.action.resource.table
    table_allowed(table)
    table.tableName != "flights"
    expression := sprintf("flight_id IN (SELECT flight_id FROM iceberg.%s.flights WHERE %s)", [lookup_schema(table.schemaName), scope_predicate])
}

masked_columns := {"tail", "recording", "source_file"} if {
    input.context.identity.user == "operations_analyst"
}

masked_columns := {"flight_no", "origin", "destination"} if {
    input.context.identity.user == "engineering_analyst"
}

masked_columns := {"recording", "source_file"} if {
    input.context.identity.user == "safety_analyst"
}

# Apply column classification consistently to both Silver and Gold.
columnMask := {"expression": "'REDACTED'"} if {
    column := input.action.resource.column
    table_allowed(column)
    column.columnName in masked_columns
}

# IDs contain the tail number. A stable pseudonym preserves joins for Operations.
columnMask := {"expression": "lower(to_hex(sha256(to_utf8(flight_id))))"} if {
    input.context.identity.user == "operations_analyst"
    column := input.action.resource.column
    table_allowed(column)
    column.columnName == "flight_id"
}

# Wide QAR tables must not generate one HTTP request per column.
batchColumnMasks contains {"index": i, "viewExpression": mask} if {
    some i
    resource := input.action.filterResources[i]
    mask := columnMask with input.action.resource as resource
}

batch contains i if {
    input.action.operation != "FilterColumns"
    some i
    resource := input.action.filterResources[i]
    allow with input.action.resource as resource
}

# FilterColumns returns column indices, not the single table's index.
batch contains i if {
    input.action.operation == "FilterColumns"
    count(input.action.filterResources) == 1
    table := input.action.filterResources[0].table
    some i
    column := table.columns[i]
    resource := {"table": object.union(table, {"columns": [column]})}
    allow with input.action.resource as resource
}
