package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.ExerciseType

@Composable
fun ExerciseVariationInfo(
    exerciseType: ExerciseType,
    targetRepRange: String?,
    equipmentName: String?,
    accessoryNames: List<String>,
    modifier: Modifier = Modifier,
    definitionName: String? = null,
    displayName: String? = null,
) {
    val equipment = equipmentName?.takeIf { it.isNotBlank() } ?: "None"
    val accessories = accessoryNames.filter { it.isNotBlank() }.distinct()
    val libraryName = definitionName
        ?.takeIf { it.isNotBlank() && it != displayName }

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        VariationDetailRow(label = "Type") {
            VariationDetailValue(exerciseType.variationTypeLabel())
        }
        if (exerciseType == ExerciseType.WEIGHT || exerciseType == ExerciseType.BODY_WEIGHT) {
            VariationDetailRow(label = "Target reps") {
                VariationDetailValue(targetRepRange?.takeIf { it.isNotBlank() } ?: "Not set")
            }
        }
        VariationDetailRow(label = "Equipment") {
            VariationDetailValue(equipment)
        }
        if (accessories.isNotEmpty()) {
            VariationDetailRow(label = "Accessories") {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    accessories.forEach { accessory ->
                        VariationDetailValue(accessory)
                    }
                }
            }
        }
        libraryName?.let { name ->
            VariationDetailRow(label = "Library exercise") {
                VariationDetailValue(name)
            }
        }
    }
}

@Composable
private fun VariationDetailRow(
    label: String,
    content: @Composable () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            text = label,
            modifier = Modifier.width(112.dp),
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Column(modifier = Modifier.weight(1f)) {
            content()
        }
    }
}

@Composable
private fun VariationDetailValue(value: String) {
    Text(
        text = value,
        style = MaterialTheme.typography.bodyLarge,
        color = MaterialTheme.colorScheme.onSurface,
    )
}

private fun ExerciseType.variationTypeLabel(): String = when (this) {
    ExerciseType.WEIGHT -> "Weight"
    ExerciseType.BODY_WEIGHT -> "Body weight"
    ExerciseType.COUNTUP -> "Count up"
    ExerciseType.COUNTDOWN -> "Count down"
}
