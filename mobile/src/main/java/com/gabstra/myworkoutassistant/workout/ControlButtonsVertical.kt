package com.gabstra.myworkoutassistant.workout

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
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.repeatActionOnLongPressOrTap
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
                .size(140.dp, 70.dp)
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
                    .size(70.dp)
                    .clip(CircleShape)
                    .background(Green),
                contentAlignment = Alignment.Center
            ) {
                Icon(modifier = Modifier.size(35.dp), imageVector = Icons.Filled.ArrowUpward, contentDescription = "Add")
            }
        }
        Box(
            modifier = Modifier.fillMaxWidth().padding(vertical = 10.dp),
            contentAlignment = Alignment.Center
        ) {
            content()
        }
        Box(
            modifier = Modifier
                .size(140.dp, 70.dp)
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
                    .size(70.dp)
                    .clip(CircleShape)
                    .background(Red),
                contentAlignment = Alignment.Center
            ) {
                Icon(modifier = Modifier.size(35.dp),imageVector = Icons.Filled.ArrowDownward, contentDescription = "Subtract")
            }
        }

    }
}