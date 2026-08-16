'''

'''


import random

def random_pick(NumOfPicks:int, List:list)->list:
    """
    Randomly pick elements from a list.

    Parameters:
    NumOfPicks (int): The number of elements after picking.
    List (list): The list from which to pick elements.

    Returns:
    list: A list containing the randomly picked elements.
    """
    if NumOfPicks >= len(List):
        return List  # Return the entire list if NumOfPicks is greater than or equal to the length of the list
    
    NumOfPicked = 0
    output = []
    while NumOfPicked < NumOfPicks:
        picked_element = random.choice(List)
        output.append(picked_element)
        NumOfPicked += 1
        List.remove(picked_element)  # Remove the picked element to avoid duplicates
    
    return output

