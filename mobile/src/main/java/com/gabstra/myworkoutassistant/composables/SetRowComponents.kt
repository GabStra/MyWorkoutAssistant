package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.clickable
import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.shape.RoundedCornerShape
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.workout.ScalableText
import java.util.UUID

sealed interface SetTableRowUiModel {
    data class Data(
        val identifier: String,
        val primaryValue: String,
        val secondaryValue: String? = null,
        val primaryLabel: String? = null,
        val secondaryLabel: String? = null,
        val monospacePrimary: Boolean = false,
        val onClick: (() -> Unit)? = null,
    ) : SetTableRowUiModel

    data class Rest(
        val text: String,
    ) : SetTableRowUiModel
}

data class SetPreviewItemUiModel(
    val setId: UUID = UUID(0L, 0L),
    val rows: List<SetTableRowUiModel>,
    val usesDashedContainer: Boolean = false,
    val isGroupedUnilateral: Boolean = false,
)

data class SetTableHeaderUiModel(
    val setLabel: String = "SET",
    val primaryLabel: String,
    val secondaryLabel: String? = null,
)

enum class SetTablePresentation {
    COMPACT,
    REVIEW,
    WORKOUT,
}

private val DefaultSetTableHeader = SetTableHeaderUiModel(
    primaryLabel = "RESULT",
    secondaryLabel = "DETAIL",
)

private const val SetColumnWeight = 1f
private const val WeightColumnWeight = 2f
private const val RepsColumnWeight = 1f
private const val TimeColumnWeight = 3f

fun inferSetTableHeader(rows: List<SetTableRowUiModel>): SetTableHeaderUiModel {
    val dataRows = rows.filterIsInstance<SetTableRowUiModel.Data>()
    if (dataRows.isEmpty()) return DefaultSetTableHeader

    val hasSecondary = dataRows.any { !it.secondaryValue.isNullOrBlank() }
    val hasPrimaryOnly = dataRows.any { it.secondaryValue.isNullOrBlank() }
    val explicitPrimaryLabel = dataRows.mapNotNull { it.primaryLabel }.distinct().singleOrNull()
    val explicitSecondaryLabel = dataRows.mapNotNull { it.secondaryLabel }.distinct().singleOrNull()

    if (explicitPrimaryLabel != null) {
        return SetTableHeaderUiModel(
            primaryLabel = explicitPrimaryLabel,
            secondaryLabel = explicitSecondaryLabel,
        )
    }

    return when {
        hasSecondary && !hasPrimaryOnly -> SetTableHeaderUiModel(
            primaryLabel = "LOAD",
            secondaryLabel = "REPS"
        )
        !hasSecondary -> SetTableHeaderUiModel(
            primaryLabel = "DURATION",
            secondaryLabel = null
        )
        else -> DefaultSetTableHeader
    }
}

@Composable
fun SetTable(
    rows: List<SetTableRowUiModel>,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    header: SetTableHeaderUiModel = inferSetTableHeader(rows),
    presentation: SetTablePresentation = SetTablePresentation.COMPACT,
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
    val tableShape = RoundedCornerShape(14.dp)

    @Composable
    fun CompactTableContent() {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(tableShape)
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.42f))
                .padding(vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            SetTableHeaderRow(
                header = header,
                headerColor = headerColor,
            )
            rows.forEach { row ->
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

            }
        }
    }

    Column(modifier = modifier.fillMaxWidth()) {
        when (presentation) {
            SetTablePresentation.COMPACT -> CompactTableContent()
            SetTablePresentation.REVIEW -> ReviewSetTableContent(
                rows = rows,
                header = header,
                headerColor = headerColor,
                contentColor = contentColor,
            )
            SetTablePresentation.WORKOUT -> WorkoutSetTableContent(
                rows = rows,
                header = header,
                headerColor = headerColor,
                contentColor = contentColor,
            )
        }
    }
}

@Composable
private fun ReviewSetTableContent(
    rows: List<SetTableRowUiModel>,
    header: SetTableHeaderUiModel,
    headerColor: androidx.compose.ui.graphics.Color,
    contentColor: androidx.compose.ui.graphics.Color,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        SetTableHeaderRow(header = header, headerColor = headerColor)
        rows.forEach { row ->
            ReviewSetRow(row = row, contentColor = contentColor)
        }
    }
}

@Composable
private fun ReviewSetRow(
    row: SetTableRowUiModel,
    contentColor: androidx.compose.ui.graphics.Color,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(12.dp)
    val baseModifier = modifier
        .fillMaxWidth()
        .heightIn(min = 44.dp)
        .clip(shape)
        .background(MaterialTheme.colorScheme.surfaceVariant)

    when (row) {
        is SetTableRowUiModel.Data -> SetTableDataRow(
            row = row,
            textColor = contentColor,
            modifier = baseModifier,
        )

        is SetTableRowUiModel.Rest -> Text(
            text = row.text,
            modifier = baseModifier.padding(horizontal = 14.dp, vertical = 10.dp),
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun WorkoutSetTableContent(
    rows: List<SetTableRowUiModel>,
    header: SetTableHeaderUiModel,
    headerColor: androidx.compose.ui.graphics.Color,
    contentColor: androidx.compose.ui.graphics.Color,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        WorkoutSetTableHeaderRow(header = header, headerColor = headerColor)
        rows.forEach { row ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(46.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val rowModifier = Modifier
                    .fillMaxWidth()
                    .height(42.dp)
                    .clip(MaterialTheme.shapes.extraLarge)
                    .background(MaterialTheme.colorScheme.background)
                    .border(
                        BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                        MaterialTheme.shapes.extraLarge,
                    )

                when (row) {
                    is SetTableRowUiModel.Data -> WorkoutSetDataRow(
                        row = row,
                        modifier = rowModifier,
                        textColor = contentColor,
                    )

                    is SetTableRowUiModel.Rest -> ScalableText(
                        text = row.text,
                        modifier = rowModifier
                            .fillMaxSize()
                            .padding(1.dp),
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                        color = contentColor,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        }
    }
}

@Composable
private fun WorkoutSetTableHeaderRow(
    header: SetTableHeaderUiModel,
    headerColor: androidx.compose.ui.graphics.Color,
) {
    val hasSecondaryColumn = header.secondaryLabel != null
    val primaryColumnWeight = if (hasSecondaryColumn) WeightColumnWeight else TimeColumnWeight
    val headerStyle = MaterialTheme.typography.titleSmall.copy(lineHeight = 18.sp)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "SET",
            modifier = Modifier.weight(SetColumnWeight),
            style = headerStyle,
            color = headerColor,
            textAlign = TextAlign.Center,
        )
        Text(
            text = if (hasSecondaryColumn) "WEIGHT (KG)" else "TIME (HH:MM:SS)",
            modifier = Modifier.weight(primaryColumnWeight),
            style = headerStyle,
            color = headerColor,
            textAlign = TextAlign.Center,
        )
        if (hasSecondaryColumn) {
            Text(
                text = "REPS",
                modifier = Modifier.weight(RepsColumnWeight),
                style = headerStyle,
                color = headerColor,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun WorkoutSetDataRow(
    row: SetTableRowUiModel.Data,
    modifier: Modifier,
    textColor: androidx.compose.ui.graphics.Color,
) {
    val hasSecondaryColumn = !row.secondaryValue.isNullOrBlank()
    val primaryColumnWeight = if (hasSecondaryColumn) WeightColumnWeight else TimeColumnWeight
    val baseStyle = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold)
    val primaryStyle = if (row.monospacePrimary) {
        baseStyle.copy(fontFamily = FontFamily.Monospace)
    } else {
        baseStyle
    }
    val clickableModifier = row.onClick?.let { modifier.clickable(onClick = it) } ?: modifier

    Row(
        modifier = clickableModifier,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ScalableText(
            text = row.identifier,
            modifier = Modifier.weight(SetColumnWeight),
            style = baseStyle,
            color = textColor,
            textAlign = TextAlign.Center,
        )
        ScalableText(
            text = row.primaryValue,
            modifier = Modifier.weight(primaryColumnWeight),
            style = primaryStyle,
            color = textColor,
            textAlign = TextAlign.Center,
        )
        if (hasSecondaryColumn) {
            ScalableText(
                text = row.secondaryValue.orEmpty(),
                modifier = Modifier.weight(RepsColumnWeight),
                style = baseStyle,
                color = textColor,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
fun SetTableHeaderRow(
    header: SetTableHeaderUiModel,
    headerColor: androidx.compose.ui.graphics.Color,
) {
    val hasSecondaryColumn = header.secondaryLabel != null
    val primaryColumnWeight = if (hasSecondaryColumn) WeightColumnWeight else TimeColumnWeight
    val labelStyle = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.SemiBold)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Text(
            text = header.setLabel,
            modifier = Modifier.weight(SetColumnWeight),
            style = labelStyle,
            color = headerColor,
            textAlign = TextAlign.Center,
        )
        Text(
            text = header.primaryLabel,
            modifier = Modifier.weight(primaryColumnWeight),
            style = labelStyle,
            color = headerColor,
            textAlign = TextAlign.Center,
        )
        val secondaryLabel = header.secondaryLabel
        if (secondaryLabel != null) {
            Text(
                text = secondaryLabel,
                modifier = Modifier.weight(RepsColumnWeight),
                style = labelStyle,
                color = headerColor,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun SetTableDataRow(
    row: SetTableRowUiModel.Data,
    textColor: androidx.compose.ui.graphics.Color,
    modifier: Modifier = Modifier,
) {
    val hasSecondaryColumn = !row.secondaryValue.isNullOrBlank()
    val primaryColumnWeight = if (hasSecondaryColumn) WeightColumnWeight else TimeColumnWeight

    val rowModifier = if (row.onClick != null) {
        modifier
            .fillMaxWidth()
            .clickable(onClick = row.onClick)
            .padding(horizontal = 14.dp, vertical = 11.dp)
    } else {
        modifier
            .fillMaxWidth()
            .padding(horizontal = 14.dp, vertical = 11.dp)
    }

    val primaryStyle = MaterialTheme.typography.bodyLarge.let { base ->
        if (row.monospacePrimary) base.copy(fontFamily = FontFamily.Monospace) else base
    }

    Column(modifier = rowModifier) {
        Row(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = row.identifier,
                modifier = Modifier.weight(SetColumnWeight),
                style = MaterialTheme.typography.bodyLarge,
                color = textColor,
                textAlign = TextAlign.Center,
            )
            Text(
                text = row.primaryValue,
                modifier = Modifier.weight(primaryColumnWeight),
                style = primaryStyle,
                color = textColor,
                textAlign = TextAlign.Center,
            )
            if (hasSecondaryColumn) {
                Text(
                    text = row.secondaryValue.orEmpty(),
                    modifier = Modifier.weight(RepsColumnWeight),
                    style = MaterialTheme.typography.bodyLarge,
                    color = textColor,
                    textAlign = TextAlign.Center,
                )
            }
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
            .padding(horizontal = 14.dp, vertical = 7.dp),
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
    )
}

@Composable
private fun SetPreviewRowsContent(
    rows: List<SetTableRowUiModel>,
    enabled: Boolean,
) {
    val contentColor = if (enabled) {
        MaterialTheme.colorScheme.onSurface
    } else {
        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
    }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        rows.forEach { row ->
            when (row) {
                is SetTableRowUiModel.Data -> {
                    val rowForDisplay = if (row.onClick != null) row.copy(onClick = null) else row
                    ReviewSetRow(row = rowForDisplay, contentColor = contentColor)
                }

                is SetTableRowUiModel.Rest -> ReviewSetRow(row = row, contentColor = contentColor)
            }

        }
    }
}

@Composable
fun SetPreviewItemCard(
    item: SetPreviewItemUiModel,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val surfaceModifier = modifier.fillMaxWidth()
    if (item.usesDashedContainer) {
        DashedCard(
            modifier = surfaceModifier,
            enabled = enabled,
        ) {
            SetPreviewRowsContent(rows = item.rows, enabled = enabled)
        }
    } else {
        Column(modifier = surfaceModifier) {
            SetPreviewRowsContent(rows = item.rows, enabled = enabled)
        }
    }
}

/**
 * One row of the exercise set table (same layout as [SetTable]), for use in selectable lists
 * where each set is a separate item (e.g. exercise detail overview).
 */
@Composable
fun SetPreviewTableRow(
    row: SetTableRowUiModel,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    SetPreviewItemCard(
        item = SetPreviewItemUiModel(
            rows = listOf(row),
        ),
        modifier = modifier,
        enabled = enabled,
    )
}

data class SetMetricUiModel(
    val label: String,
    val value: String,
)

data class SetRowUiModel(
    val identifier: String,
    val metrics: List<SetMetricUiModel>,
)

@Composable
fun SetRestRowCard(
    restText: String,
    modifier: Modifier = Modifier,
    textModifier : Modifier = Modifier,
    enabled: Boolean = true,
) {
    val textColor = if (enabled) {
        MaterialTheme.colorScheme.onBackground
    } else {
        DisabledContentGray
    }

    StyledCard(
        modifier = modifier,
        enabled = enabled,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            Text(
                text = restText,
                modifier = textModifier,
                style = MaterialTheme.typography.titleMedium,
                color = textColor,
                textAlign = TextAlign.Center
            )
        }
    }
}
