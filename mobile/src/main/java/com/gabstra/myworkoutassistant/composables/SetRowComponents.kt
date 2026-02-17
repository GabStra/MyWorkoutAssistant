package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

sealed interface SetTableRowUiModel {
    data class Data(
        val identifier: String,
        val primaryValue: String,
        val secondaryValue: String? = null,
        val monospacePrimary: Boolean = false,
        val onClick: (() -> Unit)? = null,
        val secondaryText: String? = null,
    ) : SetTableRowUiModel

    data class Rest(
        val text: String,
    ) : SetTableRowUiModel
}

data class SetTableHeaderUiModel(
    val setLabel: String = "SET",
    val primaryLabel: String,
    val secondaryLabel: String? = null,
)

private val DefaultSetTableHeader = SetTableHeaderUiModel(
    primaryLabel = "VALUE",
    secondaryLabel = "DETAIL",
)

fun inferSetTableHeader(rows: List<SetTableRowUiModel>): SetTableHeaderUiModel {
    val dataRows = rows.filterIsInstance<SetTableRowUiModel.Data>()
    if (dataRows.isEmpty()) return DefaultSetTableHeader

    val hasSecondary = dataRows.any { !it.secondaryValue.isNullOrBlank() }
    val hasPrimaryOnly = dataRows.any { it.secondaryValue.isNullOrBlank() }

    return when {
        hasSecondary && !hasPrimaryOnly -> SetTableHeaderUiModel(primaryLabel = "WEIGHT", secondaryLabel = "REPS")
        !hasSecondary -> SetTableHeaderUiModel(primaryLabel = "TIME", secondaryLabel = null)
        else -> DefaultSetTableHeader
    }
}

@Composable
fun SetTable(
    rows: List<SetTableRowUiModel>,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    header: SetTableHeaderUiModel = inferSetTableHeader(rows),
) {
    if (rows.isEmpty()) return

    val headerColor = if (enabled) {
        MaterialTheme.colorScheme.onSurfaceVariant
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
    }
    val contentColor = if (enabled) {
        MaterialTheme.colorScheme.onSurface
    } else {
        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    }
    val dividerColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.8f)

    SecondarySurface(
        modifier = modifier.fillMaxWidth(),
        enabled = enabled,
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            SetTableHeaderRow(
                header = header,
                headerColor = headerColor,
            )
            HorizontalDivider(color = dividerColor)

            rows.forEachIndexed { index, row ->
                when (row) {
                    is SetTableRowUiModel.Data -> SetTableDataRow(
                        row = row,
                        textColor = contentColor,
                    )

                    is SetTableRowUiModel.Rest -> SetTableRestRow(
                        row = row,
                        textColor = contentColor,
                    )
                }

                if (index < rows.lastIndex) {
                    HorizontalDivider(color = dividerColor)
                }
            }
        }
    }
}

@Composable
private fun SetTableHeaderRow(
    header: SetTableHeaderUiModel,
    headerColor: androidx.compose.ui.graphics.Color,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 9.dp),
    ) {
        Text(
            text = header.setLabel,
            modifier = Modifier.weight(0.8f),
            style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.SemiBold),
            color = headerColor,
            textAlign = TextAlign.Center,
        )
        Text(
            text = header.primaryLabel,
            modifier = Modifier.weight(1.2f),
            style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.SemiBold),
            color = headerColor,
            textAlign = TextAlign.Center,
        )
        Text(
            text = header.secondaryLabel ?: "",
            modifier = Modifier.weight(1f),
            style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.SemiBold),
            color = headerColor,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun SetTableDataRow(
    row: SetTableRowUiModel.Data,
    textColor: androidx.compose.ui.graphics.Color,
) {
    val rowModifier = if (row.onClick != null) {
        Modifier
            .fillMaxWidth()
            .clickable(onClick = row.onClick)
            .padding(horizontal = 12.dp, vertical = 9.dp)
    } else {
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 9.dp)
    }

    Column(modifier = rowModifier) {
        Row(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = row.identifier,
                modifier = Modifier.weight(0.8f),
                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                color = textColor,
                textAlign = TextAlign.Center,
            )
            Text(
                text = row.primaryValue,
                modifier = Modifier.weight(1.2f),
                style = MaterialTheme.typography.bodyMedium.copy(
                    fontWeight = FontWeight.SemiBold,
                    fontFamily = if (row.monospacePrimary) FontFamily.Monospace else null,
                ),
                color = textColor,
                textAlign = TextAlign.Center,
            )
            Text(
                text = row.secondaryValue.orEmpty(),
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold),
                color = textColor,
                textAlign = TextAlign.Center,
            )
        }

        if (!row.secondaryText.isNullOrBlank()) {
            Text(
                text = row.secondaryText,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 3.dp),
                style = MaterialTheme.typography.bodySmall,
                color = textColor,
                textAlign = TextAlign.Start,
            )
        }
    }
}

@Composable
private fun SetTableRestRow(
    row: SetTableRowUiModel.Rest,
    textColor: androidx.compose.ui.graphics.Color,
) {
    Text(
        text = row.text,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 9.dp),
        style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
        color = textColor,
        textAlign = TextAlign.Center,
    )
}

data class SetMetricUiModel(
    val label: String,
    val value: String,
)

data class SetRowUiModel(
    val identifier: String,
    val metrics: List<SetMetricUiModel>,
    val secondaryText: String? = null,
)

@Composable
fun SetRestRowCard(
    restText: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val textColor = if (enabled) {
        MaterialTheme.colorScheme.onSurface
    } else {
        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    }

    SecondarySurface(
        modifier = modifier.fillMaxWidth(),
        enabled = enabled,
    ) {
        Text(
            text = restText,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 9.dp),
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
            color = textColor,
            textAlign = TextAlign.Center
        )
    }
}
