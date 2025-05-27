package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type
import java.util.UUID

class EquipmentAdapter : JsonSerializer<WeightLoadedEquipment>, JsonDeserializer<WeightLoadedEquipment> {
    override fun serialize(src: WeightLoadedEquipment, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        return JsonObject().apply {
            addProperty("id", src.id.toString())
            addProperty("type", src.type.name)
            addProperty("name", src.name)

            when (src.type) {
                EquipmentType.BARBELL -> {
                    val barbell = src as Barbell
                    add("availablePlates", context.serialize(barbell.availablePlates))
                    addProperty("barWeight", barbell.barWeight)
                    addProperty("barLength", barbell.barLength)
                }
                EquipmentType.DUMBBELLS -> {
                    val dumbbells = src as Dumbbells
                    addProperty("maxExtraWeightsPerLoadingPoint", dumbbells.maxExtraWeightsPerLoadingPoint)
                    add("extraWeights", context.serialize(dumbbells.extraWeights))
                    add("dumbbells", context.serialize(dumbbells.availableDumbbells))
                }
                EquipmentType.DUMBBELL -> {
                    val dumbbell = src as Dumbbell
                    addProperty("maxExtraWeightsPerLoadingPoint", dumbbell.maxExtraWeightsPerLoadingPoint)
                    add("extraWeights", context.serialize(dumbbell.extraWeights))
                    add("dumbbells", context.serialize(dumbbell.availableDumbbells))
                }
                EquipmentType.PLATELOADEDCABLE -> {
                    val plateLoadedCable = src as PlateLoadedCable
                    add("availablePlates", context.serialize(plateLoadedCable.availablePlates))
                    addProperty("barLength", plateLoadedCable.barLength)
                }
                EquipmentType.WEIGHTVEST -> {
                    val weightVest = src as WeightVest
                    add("availableWeights", context.serialize(weightVest.availableWeights))
                }
                EquipmentType.MACHINE -> {
                    val machine = src as Machine
                    add("availableWeights", context.serialize(machine.availableWeights))
                    addProperty("maxExtraWeightsPerLoadingPoint", machine.maxExtraWeightsPerLoadingPoint)
                    add("extraWeights", context.serialize(machine.extraWeights))
                }
                EquipmentType.IRONNECK -> TODO()
            }
        }
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): WeightLoadedEquipment {
        val obj = json.asJsonObject
        val id = UUID.fromString(obj.get("id").asString)
        val name = obj.get("name").asString


        val baseWeightListType = object : TypeToken<List<BaseWeight>>() {}.type

        return when (EquipmentType.valueOf(obj.get("type").asString)) {
            EquipmentType.DUMBBELLS -> {
                val maxExtraWeightsPerLoadingPoint = obj.get("maxExtraWeightsPerLoadingPoint").asInt

                Dumbbells(
                    id = id,
                    name = name,
                    availableDumbbells = context.deserialize(obj.get("dumbbells"), baseWeightListType),
                    extraWeights =  context.deserialize<List<BaseWeight>>(obj.get("extraWeights"), baseWeightListType),
                    maxExtraWeightsPerLoadingPoint = maxExtraWeightsPerLoadingPoint,
                )
            }

            EquipmentType.BARBELL -> {
                val plateListType = object : TypeToken<List<Plate>>() {}.type

                Barbell(
                    id = id,
                    name = name,
                    availablePlates = context.deserialize(obj.get("availablePlates"), plateListType),
                    barLength = obj.get("barLength").asInt,
                    barWeight = if(obj.has("barWeight")){  obj.get("barWeight").asDouble } else{ 0.0 },
                )
            }

            EquipmentType.DUMBBELL ->{
                val maxExtraWeightsPerLoadingPoint = obj.get("maxExtraWeightsPerLoadingPoint").asInt

                Dumbbell(
                    id = id,
                    name = name,
                    availableDumbbells = context.deserialize(obj.get("dumbbells"), baseWeightListType),
                    extraWeights =  context.deserialize<List<BaseWeight>>(obj.get("extraWeights"), baseWeightListType),
                    maxExtraWeightsPerLoadingPoint = maxExtraWeightsPerLoadingPoint,
                )
            }

            EquipmentType.WEIGHTVEST ->
                WeightVest(
                    id = id,
                    name = name,
                    availableWeights = context.deserialize(obj.get("availableWeights"), baseWeightListType),
                )
            EquipmentType.MACHINE -> {
                val maxExtraWeightsPerLoadingPoint = obj.get("maxExtraWeightsPerLoadingPoint").asInt

                Machine(
                    id = id,
                    name = name,
                    availableWeights = context.deserialize(obj.get("availableWeights"), baseWeightListType),
                    extraWeights =  context.deserialize<List<BaseWeight>>(obj.get("extraWeights"), baseWeightListType),
                    maxExtraWeightsPerLoadingPoint = maxExtraWeightsPerLoadingPoint,
                )
            }
            EquipmentType.IRONNECK -> TODO()
            EquipmentType.PLATELOADEDCABLE -> {
                val plateListType = object : TypeToken<List<Plate>>() {}.type

                PlateLoadedCable(
                    id = id,
                    name = name,
                    availablePlates = context.deserialize(obj.get("availablePlates"), plateListType),
                    barLength = obj.get("barLength").asInt,
                )
            }
        }
    }
}