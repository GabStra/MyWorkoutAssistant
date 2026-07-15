package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

internal val SetValueHeaderToValueSpacing = 2.5.dp

@Composable
internal fun SetValueSection(
    label: String,
    headerStyle: TextStyle,
    content: @Composable () -> Unit,
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(SetValueHeaderToValueSpacing)
    ) {
        Text(
            text = label,
            style = headerStyle,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onBackground,
        )
        content()
    }
}
