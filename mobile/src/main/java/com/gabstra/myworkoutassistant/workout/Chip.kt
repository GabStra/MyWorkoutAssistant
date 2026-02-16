package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp


@Composable
fun Chip(
    backgroundColor: Color? = null,
    content: @Composable () -> Unit
) {
    Box(
        modifier = Modifier
            .then(
                if(backgroundColor == null)
                    Modifier.border(ButtonDefaults.outlinedButtonBorder(true), MaterialTheme.shapes.extraLarge)
                else
                    Modifier
                        .background(MaterialTheme.colorScheme.background, MaterialTheme.shapes.extraLarge)
                        .border(BorderStroke(
                            width = 1.dp,
                            color = backgroundColor
                        ), MaterialTheme.shapes.extraLarge)
            ),
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
