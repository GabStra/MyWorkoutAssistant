package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Close
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
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
    onCloseClick: () -> Unit,
    content: @Composable () -> Unit
){
    val coroutineScope = rememberCoroutineScope()

    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        // Top row: minus and plus buttons side by side
        Row(
            horizontalArrangement = Arrangement.Center,
            modifier = Modifier.fillMaxWidth()
        ) {
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
                        .background(Red),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(modifier = Modifier.size(30.dp), imageVector = Icons.Filled.ArrowDownward, contentDescription = "Subtract", tint = MaterialTheme.colorScheme.onSurface)
                }
            }
            Spacer(modifier = Modifier.width(5.dp))
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
                        .background(Green),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(modifier = Modifier.size(30.dp), imageVector = Icons.Filled.ArrowUpward, contentDescription = "Add", tint = MaterialTheme.colorScheme.onSurface)
                }
            }
        }
        
        Spacer(modifier = Modifier.height(10.dp))
        
        // Middle: content
        Box(
            modifier = Modifier.fillMaxWidth().padding(vertical = 2.5.dp),
            contentAlignment = Alignment.Center
        ) {
            content()
        }
        
        Spacer(modifier = Modifier.height(10.dp))
        
        // Bottom: X button
        val contentColor = MaterialTheme.colorScheme.onSurface
        EnhancedIconButton(
            buttonSize = 50.dp,
            hitBoxScale = 1.5f,
            onClick = onCloseClick,
            buttonModifier = Modifier.clip(CircleShape),
        ) {
            Icon(modifier = Modifier.size(30.dp), imageVector = Icons.Default.Close, contentDescription = "Close", tint = contentColor)
        }
    }
}