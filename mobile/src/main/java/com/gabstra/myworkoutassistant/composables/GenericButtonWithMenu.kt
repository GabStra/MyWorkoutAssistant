package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.MediumDarkerGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray

data class MenuItem(
    val label: String,
    val onClick: () -> Unit
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GenericButtonWithMenu(
    menuItems: List<MenuItem>,
    content: @Composable () -> Unit,
    enabled: Boolean = true
) {
    var expanded by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxWidth(),
        contentAlignment = Alignment.Center
    ) {
        ExposedDropdownMenuBox(
            expanded = expanded,
            onExpandedChange = { expanded = !expanded }
        ) {
            ExposedDropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
                matchAnchorWidth = false,
                modifier = Modifier
                    .border(BorderStroke(1.dp, MediumLightGray)),
                shape = RectangleShape,
                containerColor = MediumDarkerGray
            ) {
                menuItems.forEach { item ->
                    DropdownMenuItem(
                        onClick = {
                            item.onClick()
                            expanded = false
                        },
                        text = { Text(item.label) }
                    )
                }
            }

            Button(
                colors = ButtonDefaults.buttonColors(
                    contentColor = MaterialTheme.colorScheme.background
                ),
                onClick = { expanded = !expanded },
                enabled = enabled
            ) { content() }
        }
    }
}