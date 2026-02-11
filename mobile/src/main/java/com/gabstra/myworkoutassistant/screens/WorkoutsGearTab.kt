package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.toDisplayText
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.verticalScroll

@Composable
fun WorkoutsGearTab(
    equipments: List<WeightLoadedEquipment>,
    accessories: List<AccessoryEquipment>,
    selectedEquipments: List<WeightLoadedEquipment>,
    selectedAccessories: List<AccessoryEquipment>,
    isEquipmentSelectionModeActive: Boolean,
    isAccessorySelectionModeActive: Boolean,
    appViewModel: AppViewModel,
    onEquipmentSelectionChange: (List<WeightLoadedEquipment>) -> Unit,
    onAccessorySelectionChange: (List<AccessoryEquipment>) -> Unit,
    onEquipmentSelectionModeChange: (Boolean) -> Unit,
    onAccessorySelectionModeChange: (Boolean) -> Unit
) {
    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(vertical = 10.dp)
            .verticalColumnScrollbar(scrollState)
            .verticalScroll(scrollState)
            .padding(horizontal = 15.dp)
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Equipment:",
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onBackground
        )

        if (equipments.isEmpty()) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(5.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                GenericButtonWithMenu(
                    menuItems = EquipmentType.entries.filter { it != EquipmentType.GENERIC }.map { equipmentType ->
                        MenuItem("Add ${equipmentType.toDisplayText()}") {
                            appViewModel.setScreenData(
                                ScreenData.NewEquipment(equipmentType)
                            )
                        }
                    }.toList(),
                    content = {
                        Text(
                            "Add Equipment",
                            color = MaterialTheme.colorScheme.background
                        )
                    }
                )
            }
        } else {
            GenericSelectableList(
                it = PaddingValues(0.dp, 10.dp),
                items = equipments,
                selectedItems = selectedEquipments,
                isSelectionModeActive = isEquipmentSelectionModeActive,
                onItemClick = { equipment ->
                    appViewModel.setScreenData(
                        ScreenData.EditEquipment(
                            equipment.id,
                            equipment.type
                        )
                    )
                },
                onEnableSelection = {
                    onEquipmentSelectionModeChange(true)
                },
                onDisableSelection = {
                    onEquipmentSelectionModeChange(false)
                },
                onSelectionChange = { newSelection ->
                    onEquipmentSelectionChange(newSelection)
                },
                onOrderChange = { },
                itemContent = { it, onItemClick, onItemLongClick ->
                    StyledCard(
                        modifier = Modifier.combinedClickable(
                            onClick = { onItemClick() },
                            onLongClick = { onItemLongClick() }
                        )
                    ) {
                        Text(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(15.dp)
                                .basicMarquee(iterations = Int.MAX_VALUE),
                            text = it.name,
                            color = Color.White.copy(alpha = .87f),
                            style = MaterialTheme.typography.bodyLarge,
                        )
                    }
                },
                isDragDisabled = true,
                keySelector = { equipment -> equipment.id }
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                GenericButtonWithMenu(
                    menuItems = EquipmentType.entries.filter { it != EquipmentType.GENERIC }.map { equipmentType ->
                        MenuItem("Add ${equipmentType.toDisplayText()}") {
                            appViewModel.setScreenData(
                                ScreenData.NewEquipment(equipmentType)
                            )
                        }
                    }.toList(),
                    content = {
                        Icon(
                            imageVector = Icons.Filled.Add,
                            contentDescription = "Add",
                            tint = MaterialTheme.colorScheme.background,
                        )
                    }
                )
            }
        }

        // Accessories Section
        Spacer(Modifier.height(Spacing.xl))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Spacer(Modifier.height(Spacing.lg))

        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Accessories:",
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onBackground
        )
        Spacer(Modifier.height(Spacing.md))

        if (accessories.isEmpty()) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(5.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Button(
                    onClick = {
                        appViewModel.setScreenData(
                            ScreenData.NewEquipment(EquipmentType.ACCESSORY)
                        )
                    }
                ) {
                    Text(
                        "Add Accessory",
                        color = MaterialTheme.colorScheme.background
                    )
                }
            }
        } else {
            GenericSelectableList(
                it = PaddingValues(0.dp, 10.dp),
                items = accessories,
                selectedItems = selectedAccessories,
                isSelectionModeActive = isAccessorySelectionModeActive,
                onItemClick = { accessory ->
                    appViewModel.setScreenData(
                        ScreenData.EditEquipment(
                            accessory.id,
                            EquipmentType.ACCESSORY
                        )
                    )
                },
                onEnableSelection = {
                    onAccessorySelectionModeChange(true)
                },
                onDisableSelection = {
                    onAccessorySelectionModeChange(false)
                },
                onSelectionChange = { newSelection ->
                    onAccessorySelectionChange(newSelection)
                },
                onOrderChange = { },
                itemContent = { it, onItemClick, onItemLongClick ->
                    StyledCard(
                        modifier = Modifier.combinedClickable(
                            onClick = { onItemClick() },
                            onLongClick = { onItemLongClick() }
                        )
                    ) {
                        Text(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(15.dp)
                                .basicMarquee(iterations = Int.MAX_VALUE),
                            text = it.name,
                            color = Color.White.copy(alpha = .87f),
                            style = MaterialTheme.typography.bodyLarge,
                        )
                    }
                },
                isDragDisabled = true,
                keySelector = { accessory -> accessory.id }
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Button(
                    onClick = {
                        appViewModel.setScreenData(
                            ScreenData.NewEquipment(EquipmentType.ACCESSORY)
                        )
                    }
                ) {
                    Icon(
                        imageVector = Icons.Filled.Add,
                        contentDescription = "Add",
                        tint = MaterialTheme.colorScheme.background,
                    )
                }
            }
        }
    }
}
