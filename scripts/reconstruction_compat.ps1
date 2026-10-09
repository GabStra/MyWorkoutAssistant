function ConvertTo-ReconstructionMetadataKey {
    param([string]$Key)

    return $Key.Replace("WHAM", "RECONSTRUCTION").Replace("Wham", "Reconstruction").Replace("wham", "reconstruction")
}

function Convert-ReconstructionMetadataNode {
    param([object]$Value)

    if ($null -eq $Value -or $Value -is [string] -or $Value.GetType().IsValueType) {
        return $Value
    }
    if ($Value -is [array]) {
        for ($index = 0; $index -lt $Value.Length; $index += 1) {
            $Value[$index] = Convert-ReconstructionMetadataNode $Value[$index]
        }
        return ,$Value
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $keys = @($Value.Keys)
        foreach ($key in $keys) {
            $Value[$key] = Convert-ReconstructionMetadataNode $Value[$key]
        }
        foreach ($key in $keys) {
            if ($key -isnot [string]) { continue }
            $currentKey = ConvertTo-ReconstructionMetadataKey $key
            if ($currentKey -ceq $key) { continue }
            if (-not ($keys -ccontains $currentKey)) {
                $Value[$currentKey] = $Value[$key]
            }
            $Value.Remove($key)
        }
        return $Value
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $properties = @($Value.PSObject.Properties)
        $propertyNames = @($properties | ForEach-Object { $_.Name })
        foreach ($property in $properties) {
            $property.Value = Convert-ReconstructionMetadataNode $property.Value
        }
        foreach ($property in $properties) {
            $currentKey = ConvertTo-ReconstructionMetadataKey $property.Name
            if ($currentKey -ceq $property.Name) { continue }
            if (-not ($propertyNames -ccontains $currentKey)) {
                $Value | Add-Member -MemberType NoteProperty -Name $currentKey -Value $property.Value
            }
            $Value.PSObject.Properties.Remove($property.Name)
        }
        return $Value
    }
    return $Value
}

function Convert-ReconstructionMetadata {
    [CmdletBinding()]
    param([Parameter(Mandatory, ValueFromPipeline)][object]$InputObject)

    process {
        Convert-ReconstructionMetadataNode $InputObject
    }
}
