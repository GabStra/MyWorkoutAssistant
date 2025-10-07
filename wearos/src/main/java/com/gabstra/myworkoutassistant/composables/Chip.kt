package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.MaterialTheme


@Composable
fun Chip(
    backgroundColor: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.background,
    content: @Composable () -> Unit
) {
    val useBorder = backgroundColor == MaterialTheme.colorScheme.background

    Box(
        modifier = Modifier
            .then(if(useBorder) Modifier.border(ButtonDefaults.outlinedButtonBorder(true),RoundedCornerShape(25)) else Modifier.clip(RoundedCornerShape(25)))
            .background(backgroundColor),
        contentAlignment = Alignment.Center
    ) {
        Row(
            modifier = Modifier
                .padding(5.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            content()
        }
    }
}