from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse
import db_helper
import generic_helper

app=FastAPI()

inprogress_order={}

@app.post("/")
async def handle_request(request:Request):
    payload=await request.json()

    intent = payload['queryResult']['intent']['displayName']
    dialogflow_response = payload['queryResult']['fulfillmentText'] 
    parameters = payload['queryResult']['parameters']
    output_contexts = payload['queryResult']['outputContexts']
    session_id=generic_helper.extract_session_id(output_contexts[0]['name'])

    intent_handler_dict = {
        'order.add-context: ongoing-order': add_to_order,
        'order.remove-context: ongoing-order': remove_from_order,
        'order.complete-context: ongoing-order': complete_order,
        'track.order-context: ongoing tracking': track_order,
        'new.order':new_order
    }

    return intent_handler_dict[intent](parameters, session_id, dialogflow_response)



def new_order(parameters: dict, session_id: str, dialogflow_response:str):

    if session_id in inprogress_order:
        inprogress_order[session_id] = {}
        backend_response = "Your previous order has been cleared."
    else:
        inprogress_order[session_id] = {}
        backend_response = "Starting a new order."

    combined_response = f"{backend_response} {dialogflow_response}"

    return JSONResponse(content={
        "fulfillmentText": combined_response
    })



def remove_from_order(parameters: dict, session_id: str, dialogflow_response: str):
    if session_id not in inprogress_order:
        return JSONResponse(content={
            "fulfillmentText": "I'm having trouble finding your order. Sorry! Can you place a new order, please?"
        })

    current_order = inprogress_order[session_id]
    food_items = parameters.get('food-item', [])
    quantities = parameters.get('number', [])

    if isinstance(food_items, str):
        food_items = [food_items]
   
    if not isinstance(quantities, list):
        quantities = [quantities]
    quantities = [int(q) for q in quantities]

    print(f"Food items: {food_items}")  # Debugging output
    print(f"Quantities: {quantities}")  # Debugging output
    print(f"Current order: {current_order}")  # Debugging output

    if len(food_items) != len(quantities):
        return JSONResponse(content={
            "fulfillmentText": "Sorry, I didn't receive matching quantities for the food items. Can you specify both clearly?"
        })

    removed_items = []
    no_such_items = []
    items_with_updated_quantity = []

    for item, quantity in zip(food_items, quantities):
        if item not in current_order:
            no_such_items.append(item)
        else:
            current_quantity = current_order[item]
            if current_quantity <= quantity:
                removed_items.append(item)
                del current_order[item]
            else:
                current_order[item] -= quantity
                items_with_updated_quantity.append(item)

    # Construct fulfillment text
    if removed_items:
        fulfillment_text = f'Removed {", ".join(removed_items)} from your order!'
    elif items_with_updated_quantity:
        fulfillment_text = f'Updated quantities for {", ".join(items_with_updated_quantity)} in your order. Do you need anything else?'
    else:
        fulfillment_text = "No items were removed."

    if no_such_items:
        fulfillment_text += f" Your current order does not have {', '.join(no_such_items)}."

    if not current_order:
        fulfillment_text += " Your order is empty!"
    else:
        order_str = generic_helper.get_str_from_food_dict(current_order)
        fulfillment_text += f" Here is what is left in your order: {order_str}"

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })


def complete_order(parameters:dict, session_id:str, dialogflow_response:str):
    if session_id not in inprogress_order:
        fulfillment_text="Sorry! I'm having a trouble finding your order. Can you place a new order."
    else:
        order=inprogress_order[session_id]
        order_id=save_to_db(order)
        if order_id == -1:
            fulfillment_text = "Sorry, I couldn't process your order due to a backend error. " \
                               "Please place a new order again"
        else:
            order_total = db_helper.get_total_order_price(order_id)

            fulfillment_text = f"Awesome. We have placed your order. " \
                           f"Here is your order id # {order_id}. " \
                           f"Your order total is {order_total} which you can pay at the time of delivery!"
        del inprogress_order[session_id]
    return JSONResponse(content={
        "fulfillmentText":fulfillment_text
    })
    


def save_to_db(order:dict):
    next_order_id=db_helper.get_next_order_id()

    for food_item,quantity in order.items():
        r_code=db_helper.insert_order_item(
            food_item,
            quantity,
            next_order_id
        )
        if r_code==-1:
            return -1
    db_helper.insert_order_tracking(next_order_id,"in progress")
    
    return next_order_id


word_to_num = {
    'one': 1,
    'two': 2,
    'three': 3,
    'four': 4,
    'five': 5,
    'six': 6,
    'seven': 7,
    'eight': 8,
    'nine': 9,
    'ten': 10
}

def add_to_order(parameters: dict, session_id: str, dialogflow_response: str):
    food_item = parameters["food-item"]
    quantities = parameters["number"]

    if len(food_item) != len(quantities):
        fulfillment_text = "Sorry I didn't understand. Can you specify food items and quantity clearly."
    else:
        numeric_quantities = []
        for quantity in quantities:
            
            if quantity in word_to_num:
                numeric_quantities.append(word_to_num[quantity])
            else:
                try:
                    
                    numeric_quantities.append(int(quantity))
                except ValueError:
                    
                    fulfillment_text = "Invalid quantity format. Please use numbers or number words."
                    return JSONResponse(content={"fulfillmentText": fulfillment_text})

        new_food_dict = dict(zip(food_item, numeric_quantities))
        if session_id in inprogress_order:
            current_food_dict = inprogress_order[session_id]
            current_food_dict.update(new_food_dict)
            inprogress_order[session_id] = current_food_dict
        else:
            inprogress_order[session_id] = new_food_dict

        order_str = generic_helper.get_str_from_food_dict(inprogress_order[session_id])
        fulfillment_text = f"So far you have ordered: {order_str}, do you need anything else?"

    return JSONResponse(content={"fulfillmentText": fulfillment_text})



def track_order(parameters:dict, session_id:str, dialogflow_response:str):
    order_id=int(parameters['number'])
    order_status=db_helper.get_order_status(order_id)

    if order_status:
        fulfillment_text=f"The order status for order id: {order_id} is: {order_status}"
    else:
        fulfillment_text = f"No order found with order id: {order_id}"


    return JSONResponse(content={
            "fulfillmentText": fulfillment_text
        })
