package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import com.gabstra.myworkoutassistant.data.repeatActionOnLongPressOrTap
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red


@Composable
fun ControlButtonsVertical(
    modifier: Modifier,
    onMinusTap: () -> Unit,
    onMinusLongPress: () -> Unit,
    onPlusTap: () -> Unit,
    onPlusLongPress: () -> Unit,
    content: @Composable () -> Unit
){
    val coroutineScope = rememberCoroutineScope()

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Box(
            modifier = Modifier
                .size(50.dp)
                .background(Color.Transparent)
                .repeatActionOnLongPressOrTap(
                    coroutineScope,
                    thresholdMillis = 1000,
                    intervalMillis = 150,
                    onAction = onPlusLongPress,
                    onTap = onPlusTap
                ),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .size(50.dp)
                    .clip(CircleShape)
                    .background(Green.copy(0.35f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(modifier = Modifier.size(25.dp),imageVector = Icons.Filled.ArrowUpward, contentDescription = "Add")
            }
        }
        Box(
            modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
            contentAlignment = Alignment.Center
        ) {
            content()
        }
        Box(
            modifier = Modifier
                .size(50.dp)
                .background(Color.Transparent)
                .repeatActionOnLongPressOrTap(
                    coroutineScope,
                    thresholdMillis = 1000,
                    intervalMillis = 150,
                    onAction = onMinusLongPress,
                    onTap = onMinusTap
                ),
            contentAlignment = Alignment.Center
        ) {
            Box(
                modifier = Modifier
                    .size(50.dp)
                    .clip(CircleShape)
                    .background(Red.copy(0.35f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(modifier = Modifier.size(25.dp),imageVector = Icons.Filled.ArrowDownward, contentDescription = "Subtract")
            }
        }

    }
}